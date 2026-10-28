import hashlib
import threading

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QDialog, QFileDialog  # noqa: E402

from tests.test_qt_studio import populate, wait  # noqa: E402
from tests.test_qt_studio import window as window  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_models import HASH_ROLE  # noqa: E402
from tools.qt_transfer_dialog import TransferDialog  # noqa: E402
from tools.stable_collections import encode, read_stable  # noqa: E402

A, B, C = (value * 32 for value in "abc")


@pytest.mark.parametrize("move", [False, True])
def test_qt_copy_move_filtered_selection_and_single_undo(window, monkeypatch, move):
    populate(window)
    window.map_search.setText("missing")
    wait(window)
    window.maps.selectAll()
    before = window.workspace.plan()

    def choose(dialog):
        assert dialog.hashes == (B,)
        assert "1 new additions" in dialog.summary.text()
        dialog.target.setCurrentIndex(dialog.target.findData("two"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TransferDialog, "exec", choose)
    (window.move_button if move else window.copy_button).click()
    assert window.workspace.collection("two")["Hashes"] == [C, B]
    assert (B not in window.workspace.collection("one")["Hashes"]) is move
    assert window.workspace.dirty and not window.errors
    window.undo()
    wait(window)
    assert window.workspace.plan() == before and not window.workspace.can_undo


def test_transfer_cancel_and_duplicate_destination_identity(window, monkeypatch):
    populate(window)
    window.workspace.collection("two")["Name"] = "Main"
    window.maps.selectAll()
    before = window.workspace.plan()

    def cancel(dialog):
        assert dialog.target.currentData() == "two"
        assert "collection 2" in dialog.target.currentText()
        assert "1 already in the destination" in dialog.summary.text()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(TransferDialog, "exec", cancel)
    window.copy_button.click()
    assert window.workspace.plan() == before and not window.workspace.can_undo


def test_realm_library_adds_unassigned_songs_and_marks_duplicates(window):
    document = {
        "Format": "realm",
        "SourceRealmSha256": "",
        "Collections": [{"Id": "one", "Name": "New collection", "Hashes": [A.upper()]}],
        "Beatmaps": {
            A: {"Title": "Already added", "Available": True},
            B: {"Title": "Installed outside collections", "Available": True},
            C: {"Title": "Indexed but unavailable", "Available": False},
        },
    }
    window.workspace = Workspace(document, "copied client.realm")
    window.refresh_collections()
    window.resize(960, 640)
    window.browse_button.click()
    wait(window)
    assert window.maps.columnWidth(0) >= 280
    assert window.maps.horizontalScrollBar().maximum() > 0
    assert window.library_mode and window.map_model.columnCount() == 5
    assert window.map_model.rowCount() == 1
    assert window.map_model.index(0, 0).data(HASH_ROLE) == B
    assert window.map_model.index(0, 4).data() == "Not in collection"
    window.maps.selectAll()
    window.add_library_button.click()
    wait(window)
    assert window.workspace.collection("one")["Hashes"] == [A.upper(), B]
    assert window.map_model.rowCount() == 0
    window.not_in_collection.setChecked(False)
    wait(window)
    assert window.map_model.rowCount() == 2
    assert all(window.map_model.index(i, 4).data() == "Already in collection" for i in range(2))
    window.maps.selectAll()
    undo_count = len(window.workspace._undo)
    window.add_library_button.click()
    wait(window)
    assert len(window.workspace._undo) == undo_count
    assert "2 already" in window.status.text()
    window.remove_maps()  # The library cannot accidentally remove target memberships.
    assert window.workspace.collection("one")["Hashes"] == [A.upper(), B]
    window.undo()
    wait(window)
    assert not window.workspace.dirty
    window.sort_maps(4, Qt.SortOrder.AscendingOrder)
    wait(window)
    window.browse_button.click()
    wait(window)
    assert not window.library_mode and window.map_model.columnCount() == 4
    assert window.map_model.hashes == (A.upper(),)


def test_stable_library_scan_and_add_do_not_touch_file_until_save(window, monkeypatch, tmp_path):
    source = tmp_path / "collection.db"
    original = encode([{"Name": "New collection", "Hashes": []}])
    source.write_bytes(original)
    window.load_path(str(source))
    wait(window)
    window.browse_button.click()
    wait(window)
    assert window.empty_heading.text() == "Load your game library"
    assert window.inventory_scan_button.isVisible()
    songs = tmp_path / "Songs 練習"
    songs.mkdir()
    data = b"osu file format v14\n[Metadata]\nTitle:Local song\nVersion:Hard\n"
    (songs / "map.osu").write_bytes(data)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: str(songs))
    monkeypatch.setattr(
        "tools.qt_collection_studio.QStandardPaths.writableLocation",
        lambda *_args: str(tmp_path / "cache"),
    )
    window.inventory_scan_button.click()
    wait(window)
    assert window.map_model.rowCount() == 1 and not window.workspace.dirty
    checksum = hashlib.md5(data, usedforsecurity=False).hexdigest()
    assert window.map_model.index(0, 0).data(HASH_ROLE) == checksum
    window.maps.selectAll()
    window.add_library_button.click()
    wait(window)
    assert source.read_bytes() == original and window.workspace.dirty
    window.save_button.click()
    wait(window)
    assert read_stable(source)["Collections"][0]["Hashes"] == [checksum]
    assert next(tmp_path.glob("*.backup-*.db")).read_bytes() == original
    assert (songs / "map.osu").read_bytes() == data


def test_imported_remote_metadata_does_not_appear_as_game_inventory(window):
    populate(window)
    window._imported(
        {
            "Collections": [{"Name": "Remote", "Hashes": [C]}],
            "Beatmaps": {C: {"Title": "Remote metadata", "Available": False}},
        }
    )
    window.browse_button.click()
    wait(window)
    assert window.workspace.library_hashes == {A}
    assert window.map_model.hashes == (A,)


def test_large_library_filter_uses_worker_and_keeps_event_loop_running(window, monkeypatch):
    import tools.qt_collection_studio as studio

    maps = {
        f"{number:032x}": {"Title": f"Song {number}", "Available": True} for number in range(40_000)
    }
    window.workspace = Workspace(
        {
            "Format": "realm",
            "SourceRealmSha256": "",
            "Collections": [{"Id": "one", "Name": "Empty", "Hashes": []}],
            "Beatmaps": maps,
        },
        "copied client.realm",
    )
    window.refresh_collections()
    entered, release = threading.Event(), threading.Event()
    workers, heartbeats = [], []
    original = studio.map_order

    def filter_rows(*args, **kwargs):
        workers.append(threading.get_ident())
        entered.set()
        release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(studio, "map_order", filter_rows)
    timer = QTimer()
    timer.timeout.connect(lambda: (heartbeats.append(1), release.set()))
    timer.start(20)
    window.browse_button.click()
    wait(window)
    timer.stop()
    assert entered.is_set() and heartbeats
    assert all(thread != threading.get_ident() for thread in workers)
    assert window.map_model.rowCount() == 40_000
