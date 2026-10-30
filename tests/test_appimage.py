import hashlib
import os
import subprocess

import pytest

from desktop.package_appimage import create_appdir, fetch


@pytest.mark.skipif(os.name == "nt", reason="Linux AppImage launcher")
def test_apprun_preserves_arguments_and_marks_appimage_for_safe_updates(tmp_path):
    binary = tmp_path / "payload"
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$COLLECTIONS_STUDIO_APPIMAGE" "$@"\n')
    directory = tmp_path / "Image with spaces.AppDir"
    create_appdir(binary, directory)
    result = subprocess.run(
        [directory / "AppRun", "a b", "$(not executed)"],
        env={**os.environ, "APPDIR": str(directory)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == ["1", "a b", "$(not executed)"]
    assert (directory / "usr/bin/CollectionsStudio").stat().st_mode & 0o111
    assert "Terminal=false" in (directory / "CollectionsStudio.desktop").read_text()


def test_changed_cached_packaging_tool_is_never_executed_or_redownloaded(tmp_path):
    entry = {
        "name": "tool",
        "sha256": hashlib.sha256(b"Expected").hexdigest(),
        "url": "https://invalid.test",
    }
    (tmp_path / "tool").write_bytes(b"Changed")
    with pytest.raises(ValueError, match="changed"):
        fetch(entry, tmp_path)


def test_appimage_runtime_licences_are_visible_in_existing_credits_tab(tmp_path, monkeypatch):
    from tools import credits

    docs = tmp_path / "usr/share/doc/CollectionsStudio-AppImage"
    docs.mkdir(parents=True)
    (docs / "runtime-LICENSE").write_text("Synthetic runtime MIT notice")
    monkeypatch.setenv("COLLECTIONS_STUDIO_APPIMAGE", "1")
    monkeypatch.setenv("APPDIR", str(tmp_path))
    result = credits.read_documents()
    assert len(result) == 3
    assert "Synthetic runtime MIT notice" in dict(result)["Third-party notices"]
