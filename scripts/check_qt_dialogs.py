"""Exercise Qt dialogs on an archived map and optional disposable Realm copy."""

import argparse
import json
import sys
import threading
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (  # noqa: E402
    QItemSelection,
    QItemSelectionModel,
    QPoint,
    QSettings,
    QTimer,
)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from tools.beatmap_downloads import MIRRORS, Downloader, inspect_archive, read_download_queue  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_collection_studio import StudioWindow, configure_appearance  # noqa: E402
from tools.qt_dialog_support import finish_shutdown  # noqa: E402
from tools.qt_download_dialog import DownloadDialog  # noqa: E402
from tools.qt_migration_dialog import MigrationDialog  # noqa: E402
from tools.qt_models import IDENTITY_ROLE  # noqa: E402
from tools.stable_collections import digest, encode, read_stable  # noqa: E402


def main():
    import io

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--realm-fixture", type=Path, help="An explicitly disposable closed-client copy"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "qt-dialogs-review")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = inspect_archive(args.archive)
    hashes = list(metadata)
    unknown = "3151f10743f5e6ff0081bec80741972d"
    source = output / "fixture collection.db"
    original = encode(
        [
            {"Name": "Archive sample", "Hashes": hashes[:3] + [unknown]},
            {"Name": "Practice 練習", "Hashes": []},
        ]
    )
    source.write_bytes(original)
    app = QApplication([])
    app.setApplicationName("CollectionsStudioDialogQA")
    configure_appearance(app)
    window = StudioWindow(
        settings=QSettings(str(output / "settings.ini"), QSettings.Format.IniFormat)
    )
    window.resize(1360, 900)
    window.workspace = Workspace(read_stable(source), str(source))
    window.workspace.beatmaps = metadata
    window.workspace.present_hashes = {hashes[0]}
    window.refresh_collections()
    window.show()
    images = []
    report = {
        "PlatformPlugin": app.platformName(),
        "DevicePixelRatio": window.devicePixelRatio(),
        "NativeRoundtrip": None,
    }

    def wait(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()
        if not predicate():
            raise RuntimeError("Qt verification timed out.")

    def capture(dialog, name, controls):
        app.processEvents()
        for control in controls:
            point = control.mapTo(dialog, QPoint(0, 0))
            assert point.x() >= 0 and point.y() >= 0, name
            assert point.x() + control.width() <= dialog.width(), name
            assert point.y() + control.height() <= dialog.height(), name
        path = output / name
        assert dialog.grab().save(str(path))
        images.append(str(path))

    class Response(io.BytesIO):
        headers = {}

    archive_bytes = args.archive.read_bytes()
    requests = []

    class Client:
        def open(self, url):
            requests.append(url)
            for mirror in MIRRORS:
                if mirror.lookup:
                    for checksum in [*hashes, unknown]:
                        if url == mirror.lookup.format(md5=checksum):
                            if checksum not in metadata:
                                raise urllib.error.HTTPError(
                                    url, 404, "Fixture unresolved", {}, None
                                )
                            details = metadata[checksum]
                            return Response(
                                json.dumps(
                                    {
                                        "id": details["SetId"],
                                        "title": details["Title"],
                                        "artist": details["Artist"],
                                        "beatmaps": [
                                            {
                                                "checksum": checksum,
                                                "id": details["BeatmapId"],
                                                "version": details["Difficulty"],
                                                "mode": details["Mode"],
                                            }
                                        ],
                                    }
                                ).encode()
                            )
                if url == mirror.download.format(id=metadata[hashes[0]]["SetId"]):
                    if mirror == MIRRORS[0]:
                        raise urllib.error.URLError("Fixture outage")
                    return Response(archive_bytes)
            raise RuntimeError("Unexpected fixture request")

    entered = threading.Event()

    class PausingDownloader(Downloader):
        def run(self, hashes, directory, emit, stop):
            def progress(event):
                emit(event)
                if event["kind"] == "result" and event["state"] == "Ready":
                    entered.set()
                    stop.wait(15)

            return super().run(hashes, directory, progress, stop)

    archive_folder = output / "downloads"
    archive_folder.mkdir(exist_ok=True)
    download = DownloadDialog(window, PausingDownloader(client=Client(), interval=0))
    window._open_dialog("download_dialog", download)
    download.directory.setText(str(archive_folder))
    capture(
        download,
        "downloads-queue.png",
        [download.start_button, download.resume_button, *download.mirror_flags.values()],
    )
    download.start()
    wait(lambda: entered.is_set() and bool(download.model.states))
    download.cancel()
    wait(lambda: download.job is None)
    assert len(read_download_queue(archive_folder)["hashes"]) == 3
    assert "2 pending" in download.status.text()
    capture(
        download,
        "downloads-paused.png",
        [download.start_button, download.cancel_button, download.close_button],
    )
    download.resize(920, 700)
    capture(
        download,
        "downloads-compact.png",
        [download.start_button, download.resume_button, download.close_button],
    )
    download.close()
    app.processEvents()
    resumed = DownloadDialog(window, Downloader(client=Client(), interval=0))
    window._open_dialog("download_dialog", resumed)
    resumed.restore_queue(str(archive_folder))
    wait(lambda: resumed.job is None)
    assert resumed.model.states[hashes[1]]["reused"]
    capture(
        resumed,
        "downloads-restored.png",
        [resumed.start_button, resumed.resume_button, resumed.close_button],
    )
    count = len(requests)
    resumed.start()
    wait(lambda: resumed.job is None)
    new_requests = requests[count:]
    assert not any(
        url == mirror.download.format(id=metadata[hashes[0]]["SetId"])
        for url in new_requests
        for mirror in MIRRORS
    )
    capture(resumed, "downloads-resumed.png", [resumed.retry_button, resumed.close_button])
    resumed.close()
    app.processEvents()
    report.update(
        QueueRestored=True,
        CompletedArchivesReusedWithoutDownload=True,
        ReadyDoesNotMeanInstalled=not ({hashes[1], hashes[2]} & window.workspace.present_hashes),
        OriginalStableFixtureUnchanged=source.read_bytes() == original,
    )
    print("Qt download/cancel/resume fixtures verified", flush=True)

    def confirm_fixture():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox):
                widget.button(QMessageBox.StandardButton.Yes).click()

    def run_migration(dialog):
        QTimer.singleShot(0, confirm_fixture)
        dialog.start()
        wait(lambda: dialog.job is None)
        if dialog.result is None:
            raise RuntimeError(dialog.status.text() + "\n" + dialog.details.toPlainText())
        return dialog.result

    if args.realm_fixture:
        native_source = args.realm_fixture.resolve()
        before = digest(native_source)
        native_output = output / "native"
        native_output.mkdir(exist_ok=True)

        def loaded(document):
            window.workspace = Workspace(document, str(native_source))
            window.selected = None
            window.refresh_collections()

        window._task(
            "Reading a disposable Realm fixture…",
            lambda _stop, _progress: window.backend.run("inspect", realm_copy=native_source),
            loaded,
        )
        wait(lambda: window.job is None)
        groups = window.workspace.collections
        small = sorted(
            groups, key=lambda group: (not group["Name"].startswith("Smoke"), len(group["Hashes"]))
        )[:3]
        migration = MigrationDialog(window)
        window._open_dialog("migration_dialog", migration)
        selected = QItemSelection()
        ids = {group["Id"] for group in small}
        for row in range(migration.proxy.rowCount()):
            if migration.proxy.index(row, 0).data(IDENTITY_ROLE) in ids:
                selected.select(migration.proxy.index(row, 0), migration.proxy.index(row, 1))
        migration.table.selectionModel().select(
            selected,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        migration.output_parent.setText(str(native_output))
        capture(
            migration,
            "migration-to-stable.png",
            [migration.start_button, migration.current_button, migration.close_button],
        )
        stable = run_migration(migration)
        capture(
            migration,
            "migration-stable-verified.png",
            [migration.open_button, migration.close_button],
        )
        migration.resize(900, 700)
        capture(
            migration,
            "migration-compact.png",
            [migration.start_button, migration.parent_button, migration.close_button],
        )
        migration.close()
        app.processEvents()
        window.load_path(stable["OutputFile"])
        wait(lambda: window.job is None)
        reverse = MigrationDialog(window)
        window._open_dialog("migration_dialog", reverse)
        reverse.target.setText(str(native_source))
        reverse.realm_closed.setChecked(True)
        reverse.output_parent.setText(str(native_output))
        capture(
            reverse,
            "migration-to-lazer.png",
            [reverse.realm_closed, reverse.start_button, reverse.close_button],
        )
        result = run_migration(reverse)
        capture(
            reverse, "migration-lazer-verified.png", [reverse.open_button, reverse.close_button]
        )
        assert result["AddedMemberships"] == 0
        assert digest(native_source) == before
        assert digest(stable["OutputFile"]) == stable["OutputSha256"]
        report["NativeRoundtrip"] = {
            "RealmSourceSha256": before,
            "OriginalRealmUnchanged": True,
            "Stable": stable,
            "Realm": result,
        }
        reverse.close()
        app.processEvents()
        print("Native Qt Realm → stable → Realm roundtrip verified", flush=True)
    else:
        # Inspect the reverse-direction controls without writing a fake Realm.
        migration = MigrationDialog(window)
        window._open_dialog("migration_dialog", migration)
        capture(
            migration,
            "migration-to-lazer.png",
            [migration.start_button, migration.realm_closed, migration.close_button],
        )
        migration.resize(900, 700)
        capture(
            migration, "migration-compact.png", [migration.start_button, migration.close_button]
        )
        migration.close()
        app.processEvents()
    report["Images"] = images
    report["UsesLiveGameDatabases"] = False
    (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    window.close()
    finish_shutdown(window)
    app.processEvents()
    print("Evidence:", output, flush=True)


if __name__ == "__main__":
    main()
