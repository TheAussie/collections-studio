import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools import qt_package_smoke  # noqa: E402
from tools.qt_collection_studio import StudioWindow  # noqa: E402
from tools.qt_dialog_support import finish_shutdown  # noqa: E402


@pytest.mark.parametrize("alternate_path_spelling", [False, True])
def test_packaged_unicode_save_download_and_migration_under_windows_legacy_encoding(
    monkeypatch, tmp_path, qt_app, alternate_path_spelling
):
    original_open = Path.open

    def legacy_open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", legacy_open)
    original_temporary = qt_package_smoke.tempfile.TemporaryDirectory

    @contextmanager
    def temporary_directory(*args, **options):
        with original_temporary(*args, **options) as directory:
            if alternate_path_spelling and options.get("prefix") == "Collections Studio 練習 ":
                # Opening canonicalizes this spelling. It models Windows path
                # aliases/case normalization without requiring symlink privileges.
                child = Path(directory) / "path spelling"
                child.mkdir()
                yield str(child / "..")
            else:
                yield directory

    monkeypatch.setattr(qt_package_smoke.tempfile, "TemporaryDirectory", temporary_directory)
    native_calls = []
    original_run = subprocess.run

    def native_self_test(arguments, **options):
        if arguments[-1] != "self-test":
            return original_run(arguments, **options)
        assert options["encoding"] == "utf-8"
        native_calls.append(arguments)
        # Native Realm's own tests run separately. This test covers the real Qt,
        # file, download and migration flows without requiring an installed SDK.
        return subprocess.CompletedProcess(arguments, 0, stdout="native test placeholder")

    monkeypatch.setattr(qt_package_smoke.subprocess, "run", native_self_test)
    report = tmp_path / "unicode-check.json"
    try:
        qt_package_smoke.run_smoke(report)
    finally:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, StudioWindow):
                widget.close()
                finish_shutdown(widget)
    results = json.loads(report.read_text(encoding="utf-8"))
    assert results["UnicodePathsAndNames"]
    assert results["SaveUpdatesOpenedFileWithExactBackup"]
    assert results["SaveOutputMatchesOpenedFileIdentity"]
    assert results["ResumeSkipsUnchangedZipVerification"]
    assert results["QtMigrationDetachedFixtureUi"]
    assert results["CopyMoveDuplicateHandlingAndUndo"]
    assert results["GameLibraryBrowseAddAndUndo"]
    assert results["SavedInventoryJsonReuseAndRestore"]
    assert results["VersionedUpdateDownloadAndReplacement"]
    assert results["SelectiveAndFullCollectionDbExport"]
    assert len(native_calls) == 1
