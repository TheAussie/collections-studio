import hashlib
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QItemSelection, QItemSelectionModel, QSettings, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from tests.qt_support import dispose  # noqa: E402
from tests.test_beatmap_downloads import (  # noqa: E402
    DATA_A,
    DATA_B,
    ONE,
    THREE,
    A,
    B,
    Response,
    archive_bytes,
    difficulty,
    engine,
    lookup,
)
from tests.test_collection_migration import RealmBackend, contents, realm_workspace  # noqa: E402
from tools.beatmap_downloads import QUEUE_FILE, read_download_queue  # noqa: E402
from tools.collection_migration import migrate  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_collection_studio import StudioWindow  # noqa: E402
from tools.qt_download_dialog import SAVED_SCOPE, DownloadDialog, DownloadModel  # noqa: E402
from tools.qt_jobs import Job  # noqa: E402
from tools.qt_migration_dialog import MigrationDialog  # noqa: E402
from tools.qt_models import HASH_ROLE, IDENTITY_ROLE  # noqa: E402
from tools.stable_collections import digest, encode, read_stable  # noqa: E402


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.004)
    QApplication.processEvents()
    assert predicate()


@pytest.fixture
def app(monkeypatch, tmp_path, qt_app):
    application = qt_app
    view = StudioWindow(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    view.errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: view.errors.append(_args[-1]))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes
    )
    view.workspace = Workspace(
        {
            "Format": "stable",
            "SourceRealmSha256": "",
            "Collections": [{"Id": "one", "Name": "Queue 練習", "Hashes": [A, B]}],
        },
        "",
    )
    view.refresh_collections()
    view.show()
    application.processEvents()
    yield view
    for dialog in (view.download_dialog, view.migration_dialog):
        if dialog and not dialog._closed:
            if isinstance(dialog, DownloadDialog):
                dialog.cancel()
            until(lambda dialog=dialog: dialog.job is None)
            dialog.close()
            application.processEvents()
    view.workspace._baseline = view.workspace.plan()["Collections"]
    view.close()
    view.pool.waitForDone(8000)
    application.processEvents()
    dispose(view)


def downloads(app, worker, mirrors=(ONE,)):
    dialog = DownloadDialog(app, worker, mirrors)
    app._open_dialog("download_dialog", dialog)
    QApplication.processEvents()
    return dialog


def migrations(app, function=migrate):
    dialog = MigrationDialog(app, function)
    app._open_dialog("migration_dialog", dialog)
    QApplication.processEvents()
    return dialog


def select_ids(dialog, identifiers):
    selected = QItemSelection()
    for row in range(dialog.proxy.rowCount()):
        if dialog.proxy.index(row, 0).data(IDENTITY_ROLE) in identifiers:
            selected.select(dialog.proxy.index(row, 0), dialog.proxy.index(row, 1))
    dialog.table.selectionModel().select(
        selected,
        QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
    )


def test_qt_cancel_reopen_resume_reuses_completed_archive_and_keeps_untouched_hash(
    app, monkeypatch, tmp_path
):
    data_c = difficulty("Insane", 72)
    checksum_c = hashlib.md5(data_c, usedforsecurity=False).hexdigest()
    app.workspace.collection("one")["Hashes"].append(checksum_c)
    app.workspace._baseline = app.workspace.plan()["Collections"]
    entered = threading.Event()
    count = []
    holder = []

    def archive():
        count.append(1)
        if len(count) == 1:
            return Response(archive_bytes({"hard.osu": DATA_A}))

        def paused_read():
            entered.set()
            holder[0].job.stop.wait(4)

        return Response(archive_bytes({"extra.osu": DATA_B}), on_read=paused_read)

    first = engine(
        {
            ONE.lookup.format(md5=A): lookup(),
            ONE.lookup.format(md5=B): lookup(B),
            ONE.download.format(id=7): archive,
        },
        (ONE,),
    )
    dialog = downloads(app, first)
    holder.append(dialog)
    dialog.directory.setText(str(tmp_path))
    changed_threads = []
    dialog.model.dataChanged.connect(lambda *_args: changed_threads.append(threading.get_ident()))
    dialog.start()
    until(entered.is_set)
    dialog.cancel_button.click()
    until(lambda: dialog.job is None)
    assert dialog.model.states[A]["state"] == "Ready"
    assert dialog.model.states[B]["state"] == "Cancelled"
    assert checksum_c not in dialog.model.states
    assert read_download_queue(tmp_path)["hashes"] == [A, B, checksum_c]
    assert "Paused" in dialog.status.text() and "1 pending" in dialog.status.text()
    assert not list(tmp_path.glob("*.part"))
    assert changed_threads and set(changed_threads) == {threading.get_ident()}
    dialog.close()
    QApplication.processEvents()
    assert app.download_dialog is None

    second = engine(
        {
            ONE.lookup.format(md5=B): lookup(B),
            ONE.download.format(id=7): archive_bytes({"extra.osu": DATA_B, "insane.osu": data_c}),
        },
        (ONE,),
    )
    resumed = downloads(app, second)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: str(tmp_path)
    )
    resumed.resume_button.click()
    until(lambda: resumed.job is None)
    assert resumed.scope.currentText() == SAVED_SCOPE
    assert resumed.start_button.text() == "Resume remaining"
    assert resumed.model.states[A]["state"] == "Ready" and resumed.model.states[A]["reused"]
    assert "1 downloaded" in resumed.count.text()
    resumed.start_button.click()
    until(lambda: resumed.job is None)
    assert second.client.calls == [ONE.lookup.format(md5=B), ONE.download.format(id=7)]
    assert all(resumed.model.states[h]["state"] == "Ready" for h in [A, B, checksum_c])
    assert resumed.model.index(0, 2).data() == "Already downloaded"
    assert not resumed.start_button.isEnabled()
    assert not app.workspace.present_hashes and not app.workspace.dirty
    resumed.close()
    QApplication.processEvents()
    assert app.map_model.index(0, 3).data() == "Downloaded"
    app._library_loaded(
        {"Beatmaps": {A: {"Title": "Fixture", "Available": True}}, "Scanned": 1, "ErrorCount": 0}
    )
    assert app.map_model.index(0, 3).data() == "Available"
    assert not app.errors


def test_cancel_before_worker_starts_still_saves_the_whole_queue(app, tmp_path):
    pool = QThreadPool(app)
    pool.setMaxThreadCount(1)
    app.pool = pool
    entered, release = threading.Event(), threading.Event()

    def occupy(_stop, _progress):
        entered.set()
        release.wait(4)

    blocker = Job(occupy)
    pool.start(blocker)
    assert entered.wait(2)
    worker = engine({}, (ONE,))
    dialog = downloads(app, worker)
    dialog.directory.setText(str(tmp_path))
    dialog.start()
    dialog.cancel()
    release.set()
    until(lambda: dialog.job is None)
    assert read_download_queue(tmp_path)["hashes"] == [A, B]
    assert not worker.client.calls
    assert "Paused" in dialog.status.text()


def test_download_close_waits_for_cleanup_and_cannot_discard_queue(app, tmp_path):
    entered = threading.Event()
    holder = []

    def response():
        def paused_read():
            entered.set()
            holder[0].job.stop.wait(4)

        return Response(archive_bytes(), on_read=paused_read)

    worker = engine(
        {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): response}, (ONE,)
    )
    dialog = downloads(app, worker)
    holder.append(dialog)
    dialog.directory.setText(str(tmp_path))
    dialog.start()
    until(entered.is_set)
    dialog.reject()  # Escape follows the same guarded path as the title-bar close.
    until(lambda: app.download_dialog is None)
    assert read_download_queue(tmp_path)["hashes"] == [A, B]
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.osz"))
    assert not app.workspace.downloaded


def test_download_selection_mirror_validation_and_metadata_availability(app, tmp_path):
    worker = engine(
        {ONE.lookup.format(md5=B): lookup(B), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    )
    dialog = downloads(app, worker, (ONE, THREE))
    dialog.directory.setText(str(tmp_path))
    dialog.mirror_flags[ONE.name].setChecked(False)
    dialog.start()
    assert dialog.job is None and "Enable an MD5" in dialog.status.text()
    assert not worker.client.calls
    dialog.mirror_flags[ONE.name].setChecked(True)
    dialog.mirror_flags[THREE.name].setChecked(False)
    dialog.table.selectRow(1)
    dialog.selected_button.click()
    until(lambda: dialog.job is None)
    assert read_download_queue(tmp_path)["hashes"] == [B]
    assert A not in dialog.model.states
    assert app.workspace.beatmaps[B]["Available"] is False
    assert not app.workspace.present_hashes


def test_download_events_are_bounded_batched_and_old_job_tokens_are_ignored(app, tmp_path):
    class Worker:
        def run(self, hashes, directory, emit, stop):
            for _ in range(1200):
                emit({"kind": "item", "hash": A, "state": "Resolving", "mirror": "Fixture"})
            result = {"hash": A, "state": "Failed", "message": "Unresolved fixture"}
            emit({"kind": "result", **result})
            return {
                "results": [result],
                "requested": len(hashes),
                "report_path": str(directory / "report.json"),
            }

    dialog = downloads(app, Worker())
    dialog.directory.setText(str(tmp_path))
    dialog.events.put(
        (
            "obsolete-token",
            {
                "kind": "result",
                "hash": B,
                "state": "Ready",
                "file": "must-not-apply.osz",
                "details": {},
            },
        )
    )
    dialog.start()
    until(lambda: dialog.job is None)
    assert dialog.events.maxsize == 512
    assert dialog.model.states[A]["state"] == "Failed"
    assert B not in dialog.model.states and not app.workspace.downloaded
    assert not app.errors


def test_queue_restore_error_preserves_current_scope_and_existing_file(app, monkeypatch, tmp_path):
    path = tmp_path / QUEUE_FILE
    path.write_text("{broken")
    dialog = downloads(app, engine({}))
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: str(tmp_path)
    )
    scope = dialog.scope.currentText()
    dialog.resume_queue()
    until(lambda: dialog.job is None)
    assert dialog.scope.currentText() == scope
    assert "Cannot read" in dialog.status.text()
    assert path.read_text() == "{broken"
    assert dialog.model.hashes == [A, B]


def test_large_download_model_has_no_cell_widgets_and_preserves_hashes(app):
    model = DownloadModel({})
    hashes = [f"{number:032x}" for number in range(150_001)]
    model.replace(hashes)
    table = app._table(model)
    assert model.rowCount() == 150_001
    assert model.index(150000, 0).data(HASH_ROLE) == hashes[-1]
    assert table.indexWidget(model.index(0, 0)) is None
    table.deleteLater()


def test_download_results_never_mutate_a_replaced_workspace(app, tmp_path):
    entered, release = threading.Event(), threading.Event()

    class Worker:
        def run(self, hashes, directory, emit, stop):
            entered.set()
            release.wait(4)
            result = {
                "hash": A,
                "state": "Ready",
                "file": str(directory / "7.osz"),
                "details": {"Title": "Fixture"},
            }
            emit({"kind": "result", **result})
            return {
                "results": [result],
                "report_path": str(directory / "report.json"),
                "requested": len(hashes),
            }

    dialog = downloads(app, Worker())
    dialog.directory.setText(str(tmp_path))
    dialog.start()
    until(entered.is_set)
    old = app.workspace
    app.workspace = Workspace({"Format": "stable", "SourceRealmSha256": "", "Collections": []}, "")
    app.refresh_collections()
    release.set()
    until(lambda: dialog.job is None)
    assert not app.workspace.downloaded and not old.downloaded
    assert not app.workspace.beatmaps


def test_migration_selected_unicode_empty_collections_include_staged_edits(app, tmp_path):
    app.workspace = realm_workspace(tmp_path)
    app.workspace.rename("two", "練習 🎵 revised")
    app.refresh_collections()
    before = app.workspace.plan()
    dialog = migrations(app)
    select_ids(dialog, {"two", "three"})
    dialog.output_parent.setText(str(tmp_path))
    dialog.start()
    until(lambda: dialog.job is None)
    assert contents(dialog.result["OutputFile"]) == {"練習 🎵 revised": ["b" * 32], "Empty": []}
    assert dialog.result["IncludesUnsavedEdits"]
    assert dialog.result["SelectedCollections"] == 2
    assert dialog.result["VerifiedAfterReopen"]
    assert app.workspace.plan() == before and app.workspace.dirty
    assert digest(app.workspace.source_path) == app.workspace.source_hash
    assert not app.errors


def test_migration_current_collection_and_existing_stable_merge_preserve_target(app, tmp_path):
    app.workspace = realm_workspace(tmp_path)
    app.refresh_collections()
    app.selected = "one"
    target = tmp_path / "existing collection.db"
    original = encode(
        [{"Name": "Main", "Hashes": ["a" * 32, "c" * 32]}, {"Name": "Keep", "Hashes": ["d" * 32]}]
    )
    target.write_bytes(original)
    dialog = migrations(app)
    dialog.current_button.click()
    assert dialog.selected_ids() == ["one"]
    dialog.merge_existing.setChecked(True)
    dialog.target.setText(str(target))
    dialog.output_parent.setText(str(tmp_path))
    dialog.start()
    until(lambda: dialog.job is None)
    assert contents(dialog.result["OutputFile"]) == {
        "Main": ["a" * 32, "c" * 32, "b" * 32],
        "Keep": ["d" * 32],
    }
    assert target.read_bytes() == original
    assert dialog.result["Updated"] == 1 and not app.workspace.dirty


def test_migration_stable_to_realm_requires_closed_copy_and_preserves_both_inputs(app, tmp_path):
    source = tmp_path / "collection.db"
    original = encode([{"Name": "練習", "Hashes": [A, B]}, {"Name": "Empty", "Hashes": []}])
    source.write_bytes(original)
    app.workspace = Workspace(read_stable(source), str(source))
    app.backend = RealmBackend()
    app.refresh_collections()
    target = tmp_path / "copied client.realm"
    target.write_bytes(b"Copied Realm fixture")
    dialog = migrations(app)
    dialog.target.setText(str(target))
    dialog.output_parent.setText(str(tmp_path))
    dialog.start()
    assert dialog.job is None and "Confirm that lazer is closed" in dialog.status.text()
    dialog.realm_closed.setChecked(True)
    dialog.start()
    until(lambda: dialog.job is None)
    assert app.backend.incoming == {"練習": [A, B], "Empty": []}
    assert target.read_bytes() == b"Copied Realm fixture"
    assert source.read_bytes() == original
    assert dialog.result["DestinationFormat"] == "realm"
    assert not app.workspace.dirty and not app.errors


@pytest.mark.parametrize("failure", ["stale", "existing", "declined"])
def test_migration_rejects_stale_source_existing_output_and_declined_review(
    app, monkeypatch, tmp_path, failure
):
    app.workspace = realm_workspace(tmp_path)
    app.refresh_collections()
    dialog = migrations(app)
    dialog.output_parent.setText(str(tmp_path))
    output = tmp_path / dialog.output_name
    if failure == "stale":
        Path(app.workspace.source_path).write_bytes(b"Externally changed")
    elif failure == "existing":
        output.mkdir()
    else:
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.No
        )
    dialog.start()
    until(lambda: dialog.job is None)
    assert dialog.result is None
    assert not output.exists() or not list(output.iterdir())
    if failure == "stale":
        assert app.errors and "source file changed" in app.errors[0]


def test_migration_cannot_close_during_write_and_runs_outside_ui_thread(app, tmp_path):
    app.workspace = realm_workspace(tmp_path)
    app.refresh_collections()
    entered, release = threading.Event(), threading.Event()
    worker_ids = []

    def work(*args, **options):
        worker_ids.append(threading.get_ident())
        entered.set()
        release.wait(4)
        return migrate(*args, **options)

    dialog = migrations(app, work)
    dialog.output_parent.setText(str(tmp_path))
    dialog.start()
    until(entered.is_set)
    assert not dialog.close_button.isEnabled()
    dialog.reject()
    assert not dialog._closed and "Wait" in dialog.status.text()
    app.close()
    assert not app._closed
    release.set()
    until(lambda: dialog.job is None)
    assert dialog.result["VerifiedAfterReopen"]
    assert worker_ids and worker_ids[0] != threading.get_ident()


def test_main_tools_enable_real_qt_dialogs_and_keep_last_import_scope(app):
    app._imported({"Collections": [{"Name": "Imported", "Hashes": [A]}]})
    app.download_action.trigger()
    assert app.download_dialog.scope.currentText() == "Last import"
    assert app.download_dialog.model.hashes == [A]
    assert not app.open_button.isEnabled()
    app.download_dialog.close()
    QApplication.processEvents()
    app.migrate_action.trigger()
    assert isinstance(app.migration_dialog, MigrationDialog)
