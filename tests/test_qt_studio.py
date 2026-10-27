import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from tests.qt_support import dispose  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_collection_studio import StudioWindow  # noqa: E402
from tools.qt_models import HASH_ROLE, IDENTITY_ROLE  # noqa: E402
from tools.stable_collections import encode, read_stable  # noqa: E402

A, B, C = "a" * 32, "b" * 32, "c" * 32


@pytest.fixture
def window(qt_app, monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    view = StudioWindow(settings=settings)
    view.errors = []
    monkeypatch.setattr(view, "error", view.errors.append)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes
    )
    view.show()
    qt_app.processEvents()
    yield view
    if view.workspace:
        view.workspace._baseline = view.workspace.plan()["Collections"]
    view.close()
    view.pool.waitForDone(10000)
    qt_app.processEvents()
    dispose(view)


def wait(window):
    deadline = time.monotonic() + 8
    while (
        window.job or window.row_job or window.filter_timer.isActive()
    ) and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert not window.job and not window.row_job and not window.filter_timer.isActive()


def populate(window, hashes=None):
    window.workspace = Workspace(
        {
            "Format": "stable",
            "SourceRealmSha256": "",
            "Collections": [
                {"Id": "one", "Name": "Main", "Hashes": hashes or [A.upper(), B, C]},
                {"Id": "two", "Name": "練習 🎵", "Hashes": [C]},
            ],
            "Beatmaps": {
                A: {"Title": "Known available fixture", "Difficulty": "Hard", "Available": True},
                B: {"Title": "Known missing fixture", "Difficulty": "Extra", "Available": False},
            },
        },
        "",
    )
    window.refresh_collections()


def test_model_has_explicit_statuses_and_original_hash_identity(window):
    populate(window)
    assert window.map_model.rowCount() == 3
    assert [window.map_model.index(row, 3).data() for row in range(3)] == [
        "Available",
        "Missing",
        "Unresolved",
    ]
    assert window.map_model.index(0, 0).data(HASH_ROLE) == A.upper()
    window.maps.selectRow(2)
    assert C in window.details.toPlainText()
    assert "Only the original MD5 is known" in window.details.toPlainText()
    assert window.maps.indexWidget(window.map_model.index(0, 0)) is None
    window.workspace.beatmaps[C] = {"Available": False, "Title": "", "Mode": "osu"}
    window.show_collection()
    assert window.map_model.index(2, 3).data() == "Unresolved"


def test_filter_sort_multiselection_remove_and_undo_preserve_memberships(window):
    populate(window)
    window.map_search.setText("missing")
    wait(window)
    assert window.map_model.rowCount() == 1
    assert window.map_model.index(0, 0).data(HASH_ROLE) == B
    window.maps.selectAll()
    window.remove_maps()
    assert window.workspace.collection("one")["Hashes"] == [A.upper(), C]
    assert window.workspace.collection("two")["Hashes"] == [C]
    window.undo()
    window.map_search.clear()
    window.sort_maps(3, Qt.SortOrder.DescendingOrder)
    wait(window)
    assert window.map_model.index(0, 3).data() == "Unresolved"
    window.maps.selectAll()
    assert len(window.selected_hashes()) == 3
    assert not window.workspace.dirty


def test_unicode_collection_create_rename_delete_and_undo(window, monkeypatch):
    populate(window)
    window.collection_search.setText("Main")
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *_args, **_kwargs: ("新しい collection 🎵", True)
    )
    window.new_collection()
    created_id = window.selected
    assert window.workspace.collection(created_id)["Name"] == "新しい collection 🎵"
    assert "Unsaved" in window.change_label.text()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("練習 — renamed", True))
    window.rename_collection()
    assert window.workspace.collection(created_id)["Name"] == "練習 — renamed"
    window.delete_collection()
    assert len(window.workspace.collections) == 2
    window.undo()
    assert window.workspace.collection(created_id)["Name"] == "練習 — renamed"


def test_stable_open_import_save_reopen_uses_new_copy_and_unicode_paths(
    window, monkeypatch, tmp_path
):
    source_folder = tmp_path / "source with spaces 練習"
    source_folder.mkdir()
    source = source_folder / "collection.db"
    original = encode([{"Name": "Main", "Hashes": [A.upper(), C]}])
    source.write_bytes(original)
    window.load_path(str(source))
    wait(window)
    incoming = tmp_path / "incoming.db"
    incoming.write_bytes(
        encode([{"Name": "Main", "Hashes": [A, B]}, {"Name": "空 🎵", "Hashes": []}])
    )
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(incoming), "")
    )
    window.import_file()
    wait(window)
    assert window.workspace.collections[0]["Hashes"] == [A.upper(), C, B]
    parent = tmp_path / "output with spaces 練習"
    parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: str(parent))
    window.save_copy()
    wait(window)
    assert not window.errors
    assert source.read_bytes() == original
    saved = read_stable(window.workspace.source_path)
    assert [(g["Name"], g["Hashes"]) for g in saved["Collections"]] == [
        ("Main", [A.upper(), C, B]),
        ("空 🎵", []),
    ]
    assert not window.workspace.dirty and not window.workspace.can_undo
    assert (Path(window.workspace.source_path).parent / "import-report.json").is_file()


def test_stale_source_save_keeps_unsaved_changes_and_publishes_nothing(
    window, monkeypatch, tmp_path
):
    source = tmp_path / "collection.db"
    source.write_bytes(encode([{"Name": "Main", "Hashes": [C]}]))
    window.load_path(str(source))
    wait(window)
    window.workspace.rename(window.selected, "Edited")
    source.write_bytes(b"externally changed")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: str(tmp_path)
    )
    window.save()
    wait(window)
    assert window.workspace.dirty
    assert window.errors and "source changed" in str(window.errors[0]).lower()
    assert not list(tmp_path.glob("collections-export-*"))


def test_save_button_updates_open_file_with_backup_and_no_destination_prompt(
    window, monkeypatch, tmp_path
):
    source = tmp_path / "collection.db"
    original = encode([{"Name": "Main", "Hashes": [A, C]}])
    source.write_bytes(original)
    window.load_path(str(source))
    wait(window)
    window.workspace.rename(window.selected, "Saved 練習")
    window.refresh_collections()
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: pytest.fail("Save must use the opened folder"),
    )
    assert window.save_button.text() == "Save"
    window.save_button.click()
    wait(window)
    assert not window.errors and window.workspace.source_path == str(source)
    assert read_stable(source)["Collections"][0]["Name"] == "Saved 練習"
    assert next(tmp_path.glob("*.backup-*.db")).read_bytes() == original
    assert not window.workspace.dirty and not window.workspace.can_undo
    assert "Backup:" in window.details.toPlainText()
    before = list(tmp_path.glob("*.backup-*.db"))
    window.save()
    assert list(tmp_path.glob("*.backup-*.db")) == before


def test_new_stable_save_can_cancel_or_choose_a_filename_without_overwriting(
    window, monkeypatch, tmp_path
):
    window.new_file()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
    window.save()
    assert not window.job and not window.workspace.source_path
    target = tmp_path / "New collection 練習.db"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(target), ""))
    window.save()
    wait(window)
    assert not window.errors and window.workspace.source_path == str(target)
    assert target.is_file() and not list(tmp_path.glob("*.backup-*"))


def test_cancelled_result_does_not_mutate_workspace(window):
    populate(window)
    entered = threading.Event()
    callbacks = []

    def work(stop, _progress):
        entered.set()
        stop.wait(3)
        return {"late": True}

    window._task("Test read", work, callbacks.append)
    assert entered.wait(2)
    assert not window.open_button.isEnabled()
    window.cancel_job()
    wait(window)
    assert not callbacks and not window.workspace.dirty
    assert "Cancelled" in window.status.text()


def test_closed_view_rejects_worker_results(window):
    entered = threading.Event()
    applied = []

    def work(stop, _progress):
        entered.set()
        stop.wait(3)
        return "late"

    window._task("Test read", work, applied.append)
    assert entered.wait(2)
    window.close()
    window.pool.waitForDone(3000)
    QApplication.processEvents()
    assert not applied and window._closed


def test_stale_filter_result_cannot_replace_a_different_collection(window):
    populate(window)
    window.map_search.setText("Unresolved")
    window.filter_maps()
    old_token = window.row_job.token
    window.selected = "two"
    window.show_collection()
    window._rows_finished((old_token, [0, 1, 2], None))
    wait(window)
    assert window.map_model.hashes == (C,)
    assert window.map_model.rowCount() == 1


def test_large_collection_search_and_sort_leave_event_loop_running(window, monkeypatch):
    from tools import qt_collection_studio

    original = qt_collection_studio.map_order
    workers = []

    def ordered(*args):
        workers.append(threading.get_ident())
        return original(*args)

    monkeypatch.setattr(qt_collection_studio, "map_order", ordered)
    hashes = [f"{number:032x}" for number in range(150_001)]
    populate(window, hashes)
    assert window.map_model.rowCount() == 150_001
    heartbeats = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: heartbeats.append(1) if window.row_job else None)
    timer.start(5)
    window.map_search.setText(hashes[-1])
    window.sort_maps(0, Qt.SortOrder.AscendingOrder)
    wait(window)
    timer.stop()
    assert window.map_model.rowCount() == 1
    assert window.map_model.index(0, 0).data(HASH_ROLE) == hashes[-1]
    assert heartbeats
    assert workers and all(worker != threading.get_ident() for worker in workers)
    assert window.collection_model.index(0, 0).data(IDENTITY_ROLE) == "one"


def test_credits_viewer_opens_without_collection_and_keeps_full_licence(window):
    action = next(
        action
        for action in window.tools_button.menu().actions()
        if action.text() == "Credits and licences…"
    )
    action.trigger()
    QApplication.processEvents()
    dialog = window.credits_dialog
    assert dialog.isVisible() and dialog.tabs.count() == 3
    assert "TheAussie" in dialog.tabs.widget(0).toPlainText()
    assert "MIT License" in dialog.tabs.widget(1).toPlainText()
    assert "PySide6" in dialog.tabs.widget(2).toPlainText()
    assert window.workspace is None and window.job is None
    dialog.close()
    window.show_credits()
    assert window.credits_dialog is dialog
    dialog.close()
