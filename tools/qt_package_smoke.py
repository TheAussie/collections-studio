"""Disposable package verification. No game paths, credentials, or live databases."""

import hashlib
import io
import json
import platform
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, qVersion
from PySide6.QtWidgets import QApplication, QMessageBox

from tools import beatmap_downloads
from tools.beatmap_downloads import Downloader, Mirror, read_download_queue
from tools.collection_application import load_document
from tools.collection_backend import DLL, ROOT
from tools.collection_exports import capture_export, export_collection_file
from tools.collection_workspace import Workspace
from tools.library_cache import cache_database_inventory
from tools.qt_collection_studio import StudioWindow
from tools.qt_dialog_support import finish_shutdown
from tools.qt_download_dialog import DownloadDialog
from tools.qt_export_dialog import ExportDialog
from tools.qt_migration_dialog import MigrationDialog
from tools.qt_transfer_dialog import TransferDialog
from tools.stable_collections import encode, read_stable
from tools.update_smoke import run_update_smoke


def require(condition, message):
    if not condition:
        raise RuntimeError("Packaged self-test: " + message)


def run_smoke(report_path):
    report_path = Path(report_path).resolve()
    with tempfile.TemporaryDirectory(prefix="Collections Studio 練習 ") as folder:
        folder = Path(folder)
        run_update_smoke(folder)
        data = b"osu file format v14\n[Metadata]\nBeatmapSetID:7\n"
        checksum = hashlib.md5(data, usedforsecurity=False).hexdigest()
        source = folder / "source collection.db"
        original = encode([{"Name": "練習 🎵", "Hashes": [checksum]}])
        source.write_bytes(original)
        window = StudioWindow(
            settings=QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
        )
        window.show()
        from PySide6.QtGui import QIcon

        from tools.linux_install import icon_path

        require(not QIcon(str(icon_path())).pixmap(64, 64).isNull(), "Application icon is missing.")
        if sys.platform == "linux" and getattr(sys, "frozen", False):
            from tools.linux_install import Layout, install, running_artifact, uninstall

            desktop = folder / "private Desktop"
            desktop.mkdir()
            layout = Layout(folder / "private install data", desktop)
            artifact = running_artifact()
            installed = install(layout, artifact, window.version, desktop=True)
            require(
                Path(installed["path"]).is_file(),
                "Per-user installation did not create its executable.",
            )
            require(
                layout.icon.is_file() and layout.desktop.is_file(),
                "Installation shortcuts/icon are missing.",
            )
            removed = uninstall(layout)
            require(
                not removed["kept"] and not layout.binary.exists(),
                "Uninstall left its managed executable behind.",
            )
            require(artifact.path.is_file(), "Uninstall changed the original portable file.")
        window.show_credits()
        require(window.credits_dialog is not None, "Credits viewer did not open.")
        tabs = window.credits_dialog.tabs
        require(tabs.count() == 3, "Credit/licence documents are missing.")
        require("MIT License" in tabs.widget(1).toPlainText(), "MIT licence was not bundled.")
        require("osu!collector" in tabs.widget(0).toPlainText(), "Credits were not bundled.")
        require("PySide6" in tabs.widget(2).toPlainText(), "Third-party notices were not bundled.")
        window.credits_dialog.close()
        window.load_path(str(source))
        deadline = time.monotonic() + 30
        while window.job and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        if window.job or window.workspace is None:
            raise RuntimeError("Packaged stable UI open failed.")
        window.workspace.merge(
            [{"Name": "練習 🎵", "Hashes": [checksum.upper()]}, {"Name": "空", "Hashes": []}]
        )
        window.refresh_collections()
        source_id = next(group["Id"] for group in window.workspace.collections if group["Hashes"])
        empty_id = next(
            group["Id"] for group in window.workspace.collections if not group["Hashes"]
        )
        export_plan = window.workspace.plan()
        export_path = window.workspace.source_path
        export_dirty = window.workspace.dirty
        export_ui = ExportDialog(window)
        require(
            export_ui.model.selected_ids() == {source_id, empty_id},
            "Full export omitted a collection.",
        )
        export_ui.selected_button.setChecked(True)
        export_ui.model.checked = {empty_id}
        export_ui.model.changed()
        require(
            export_ui.model.selected_ids() == {empty_id},
            "Selective export chose the wrong collection.",
        )
        export_ui.deleteLater()
        selected_export = export_collection_file(
            capture_export(window.workspace, {empty_id}), folder / "selected collection.db"
        )
        require(
            [g["Name"] for g in read_stable(selected_export["OutputFile"])["Collections"]]
            == ["空"],
            "Selected collection.db export failed verification.",
        )
        full_export = export_collection_file(
            capture_export(window.workspace), folder / "full collection.db"
        )
        require(full_export["Collections"] == 2, "Full collection.db export omitted a collection.")
        require(
            window.workspace.plan() == export_plan
            and window.workspace.source_path == export_path
            and window.workspace.dirty == export_dirty,
            "Export changed the editing session.",
        )
        transfer = TransferDialog(window, source_id, [checksum, checksum.upper()])
        require(
            transfer.target.currentData() == empty_id, "Copy dialog selected the wrong destination."
        )
        require(
            "1 new additions" in transfer.summary.text(), "Copy dialog did not deduplicate MD5s."
        )
        transfer.deleteLater()
        copied = window.workspace.transfer_maps(source_id, empty_id, [checksum, checksum.upper()])
        require(copied["added"] == 1, "Copy did not add exactly one destination membership.")
        require(
            window.workspace.transfer_maps(source_id, empty_id, [checksum])["added"] == 0,
            "Repeated copy added a duplicate.",
        )
        window.workspace.undo()
        window.workspace.transfer_maps(source_id, empty_id, [checksum], move=True)
        require(
            not window.workspace.collection(source_id)["Hashes"], "Move left its source membership."
        )
        require(
            window.workspace.collection(empty_id)["Hashes"] == [checksum],
            "Move lost the destination hash.",
        )
        window.workspace.undo()
        library_hash = "b" * 32
        window.workspace.load_inventory(
            {
                "Beatmaps": {
                    checksum: {"Title": "Already added", "Available": True},
                    library_hash: {"Title": "Library fixture", "Available": True},
                }
            }
        )
        window.refresh_collections()
        window.browse_button.click()
        deadline = time.monotonic() + 10
        while (window.row_job or window.filter_timer.isActive()) and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        require(
            window.map_model.rowCount() == 1, "Library did not filter existing collection hashes."
        )
        window.maps.selectAll()
        window.add_library_button.click()
        require(
            library_hash in window.workspace.collection(source_id)["Hashes"], "Library add failed."
        )
        window.undo()
        require(
            window.workspace.collection(source_id)["Hashes"] == [checksum], "Library undo failed."
        )
        window.browse_button.click()
        # The following download checks deliberately start with no installed
        # inventory. The library fixture above must not satisfy their missing map.
        window.workspace.load_inventory({"Beatmaps": {}})
        window.show_collection()
        require(source.read_bytes() == original, "Membership edits wrote before Save.")
        window.save_button.click()
        deadline = time.monotonic() + 30
        while window.job and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        if window.job or window.workspace.dirty:
            raise RuntimeError("Packaged Save did not complete.")
        saved = json.loads(next(folder.glob("*.save-report-*.json")).read_text(encoding="utf-8"))
        require(
            read_stable(saved["OutputFile"])["Collections"][0]["Hashes"] == [checksum],
            "The saved stable collection did not retain the expected MD5.",
        )
        if not Path(saved["OutputFile"]).samefile(source):
            raise RuntimeError(
                f"Packaged Save wrote to a different file. Opened: {source!s}; "
                f"reported: {saved['OutputFile']}"
            )
        require(
            Path(saved["BackupFile"]).read_bytes() == original,
            "The backup does not exactly match the original stable file.",
        )
        QApplication.processEvents()

        inventory_file = folder / "synthetic inventory source.db"
        inventory_file.write_bytes(b"Synthetic source identity; parsed metadata supplied below.")
        inventory_maps = {checksum: {"Title": "Saved inventory fixture", "Available": True}}
        binding = cache_database_inventory(
            inventory_file, {"Beatmaps": inventory_maps}, folder / "inventory cache"
        )
        cache_file = Path(binding["cache"])
        cache_stamp, cache_bytes = cache_file.stat().st_mtime_ns, cache_file.read_bytes()
        cache_database_inventory(
            inventory_file, {"Beatmaps": inventory_maps}, folder / "inventory cache"
        )
        require(
            (cache_file.stat().st_mtime_ns, cache_file.read_bytes()) == (cache_stamp, cache_bytes),
            "Unchanged inventory JSON was rewritten.",
        )
        inventory_file.unlink()
        restored = load_document(source, window.backend, library_source=binding)
        require(restored["Beatmaps"] == inventory_maps, "Saved library JSON did not restore.")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("fixture.osu", data)
        mirror = Mirror(
            "Fixture", "https://fixture.test/d/{id}", "https://fixture.test/md5/{md5}", "set"
        )
        calls = []

        class Response(io.BytesIO):
            headers = {}

        class Client:
            def open(self, url):
                calls.append(url)
                if "/md5/" in url:
                    return Response(
                        json.dumps({"id": 7, "beatmaps": [{"checksum": checksum}]}).encode()
                    )
                return Response(buffer.getvalue())

        inspections, original_inspect = [], beatmap_downloads.inspect_archive

        def inspect_once(*args, **kwargs):
            inspections.append(1)
            return original_inspect(*args, **kwargs)

        beatmap_downloads.inspect_archive = inspect_once
        first = Downloader((mirror,), Client(), interval=0, report_dir=folder / "reports").run(
            [checksum], folder
        )
        require(first["results"][0]["state"] == "Ready", "The fixture download did not finish.")
        count = len(calls)
        again = Downloader((mirror,), Client(), interval=0, report_dir=folder / "reports").run(
            read_download_queue(folder)["hashes"], folder
        )
        require(
            again["results"][0]["state"] == "Ready" and len(calls) == count,
            "Resuming the completed fixture failed or made an unexpected network request.",
        )
        require(len(inspections) == 1, "Resume reopened an unchanged verified ZIP archive.")

        def finish(dialog):
            deadline = time.monotonic() + 30
            while dialog.job and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.005)
            if dialog.job:
                raise RuntimeError("Packaged Qt dialog did not finish.")

        download = DownloadDialog(
            window,
            Downloader((mirror,), Client(), interval=0, report_dir=folder / "reports"),
            (mirror,),
        )
        window._open_dialog("download_dialog", download)
        download.directory.setText(str(folder))
        download.start()
        finish(download)
        require(
            download.model.states[checksum]["state"] == "Ready",
            "The Qt download dialog did not mark the fixture ready.",
        )
        require(len(calls) == count, "The Qt dialog redownloaded the completed fixture.")
        download.close()
        QApplication.processEvents()
        require(
            window.map_model.index(0, 3).data() == "Downloaded",
            "The library did not mark the completed archive as Downloaded.",
        )
        resumed = DownloadDialog(
            window,
            Downloader((mirror,), Client(), interval=0, report_dir=folder / "reports"),
            (mirror,),
        )
        window._open_dialog("download_dialog", resumed)
        resumed.restore_queue(str(folder))
        finish(resumed)
        resumed.start()
        finish(resumed)
        require(
            resumed.model.states[checksum]["state"] == "Ready" and len(calls) == count,
            "The restored Qt queue failed or redownloaded its completed fixture.",
        )
        require(len(inspections) == 1, "The restored Qt queue reopened a completed ZIP.")
        beatmap_downloads.inspect_archive = original_inspect
        resumed.close()
        QApplication.processEvents()

        # Exercise the Qt snapshot-to-stable flow with a detached fixture. Actual Realm
        # creation/schema preservation is separately covered by the native self-tests below.
        document = read_stable(saved["OutputFile"])
        document["Format"] = "realm"
        window.workspace = Workspace(document, saved["OutputFile"])
        window.refresh_collections()
        migration = MigrationDialog(window)
        window._open_dialog("migration_dialog", migration)
        migration.output_parent.setText(str(folder))

        def confirm_fixture():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QMessageBox):
                    widget.button(QMessageBox.StandardButton.Yes).click()

        QTimer.singleShot(0, confirm_fixture)
        migration.start()
        finish(migration)
        if not migration.result:
            raise RuntimeError("Qt migration self-test: " + migration.status.text())
        require(migration.result["VerifiedAfterReopen"], "Migration failed reopening verification.")
        require(migration.result["SelectedCollections"] == 2, "Migration selected the wrong count.")
        require(
            len(read_stable(migration.result["OutputFile"])["Collections"]) == 2,
            "The migrated stable file did not retain both fixture collections.",
        )
        migration.close()
        QApplication.processEvents()
        window.close()
        finish_shutdown(window)
        QApplication.processEvents()

        bundled = (
            Path(getattr(sys, "_MEIPASS", ROOT))
            / "backend"
            / (
                "realm-collection-import.exe"
                if sys.platform == "win32"
                else "realm-collection-import"
            )
        )
        command = [str(bundled)] if bundled.is_file() else ["dotnet", str(DLL)]
        try:
            native = subprocess.run(
                [*command, "self-test"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                "Packaged native Realm self-test failed:\n"
                + (error.stdout or "")
                + (error.stderr or "")
            ) from error
        report = {
            "Platform": platform.platform(),
            "Python": platform.python_version(),
            "Qt": qVersion(),
            "Frozen": bool(getattr(sys, "frozen", False)),
            "VersionedUpdateDownloadAndReplacement": True,
            "SelectiveAndFullCollectionDbExport": True,
            "StableUiOpen": True,
            "CreditsAndLicenceDocuments": True,
            "ApplicationIconBundled": True,
            "LinuxUserInstallAndUninstall": sys.platform == "linux"
            and bool(getattr(sys, "frozen", False)),
            "UnicodePathsAndNames": True,
            "ImportDedupAndEmptyCollection": True,
            "CopyMoveDuplicateHandlingAndUndo": True,
            "GameLibraryBrowseAddAndUndo": True,
            "SavedInventoryJsonReuseAndRestore": True,
            "VerifiedSaveAndSourceBackup": True,
            "SaveUpdatesOpenedFileWithExactBackup": True,
            "SaveOutputMatchesOpenedFileIdentity": True,
            "OfflineVerifiedDownloadAndResume": True,
            "QtDownloadAndRestoreUi": True,
            "ResumeSkipsUnchangedZipVerification": True,
            "QtMigrationDetachedFixtureUi": True,
            "RealmSelfTests": native.stdout.strip(),
            "UsesLiveDatabases": False,
            "Limitations": [
                "Synthetic offline download; live mirror availability is a separate test.",
                "Qt migration smoke uses a detached fixture; "
                "real Realm schemas are tested natively.",
            ],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
