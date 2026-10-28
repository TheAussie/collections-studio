import json
import time
import tkinter as tk
from pathlib import Path

import pytest

from tools import collection_studio as studio
from tools.collection_workspace import Workspace

A, B = "a" * 32, "b" * 32
DOCUMENT = {
    "SourceRealmSha256": "f" * 64,
    "Collections": [
        {"Id": "one", "Name": "Main", "Hashes": [A, B]},
        {"Id": "two", "Name": "練習 🎵", "Hashes": [B]},
    ],
    "Beatmaps": {
        A: {"Title": "Song", "Artist": "Artist", "Difficulty": "Hard", "Mode": "osu"},
    },
}


class FakeBackend:
    def __init__(self):
        self.calls = []

    def run(self, command, **options):
        self.calls.append((command, options))
        if command == "inspect":
            return DOCUMENT
        if command == "read-collections":
            return {"Collections": [{"Name": "Imported", "Hashes": [B]}]}
        if command == "edit":
            self.saved_plan = json.loads(Path(options["plan"]).read_text())
            return {
                "OutputRealm": str(options["output_directory"] / "client.realm"),
                "OutputRealmSha256": "e" * 64,
            }
        raise AssertionError(command)


@pytest.fixture
def app(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    root.withdraw()
    app = studio.CollectionStudio(root, FakeBackend())
    monkeypatch.setattr(
        studio.messagebox, "showerror", lambda *args, **kwargs: pytest.fail(str(args))
    )
    monkeypatch.setattr(studio.messagebox, "showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr(studio.messagebox, "askyesno", lambda *args, **kwargs: True)
    yield app
    root.destroy()


def finish(app):
    deadline = time.monotonic() + 3
    while app.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not app.busy
    app.root.update()


def test_gui_load_search_select_remove_and_undo(app):
    app.load("copied.realm")
    finish(app)
    assert len(app.collections.get_children()) == 2
    rows = app.maps.get_children()
    assert app.maps.item(rows[0], "values")[:3] == ("Artist — Song", "Hard", "osu")
    assert app.maps.item(rows[1], "values")[3] == "Missing"
    app.map_search.set("hard")
    assert len(app.maps.get_children()) == 1
    app.select_all_maps()
    app.remove_maps()
    assert app.workspace.collection("one")["Hashes"] == [B]
    assert app.workspace.collection("two")["Hashes"] == [B]
    app.undo()
    assert not app.workspace.dirty
    app.collection_search.set("練習")
    app.root.update()
    assert app.collections.get_children() == ("two",)
    app.delete_collection()
    assert len(app.workspace.collections) == 1
    app.undo()
    assert len(app.workspace.collections) == 2


def test_gui_import_and_save_carries_plan_and_new_destination(app, monkeypatch, tmp_path):
    from tools.stable_collections import encode

    app.workspace = Workspace(DOCUMENT, str(tmp_path / "source.realm"))
    app.refresh_collections()
    incoming = tmp_path / "incoming.db"
    incoming.write_bytes(encode([{"Name": "Imported", "Hashes": [B]}]))
    monkeypatch.setattr(studio.filedialog, "askopenfilename", lambda **kwargs: str(incoming))
    monkeypatch.setattr(studio.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    app.import_file()
    finish(app)
    assert len(app.workspace.collections) == 3
    assert app.workspace.dirty
    app.save()
    finish(app)
    command, options = app.backend.calls[-1]
    assert command == "edit"
    assert options["realm_copy"] == str(tmp_path / "source.realm")
    assert options["output_directory"].parent == tmp_path
    assert app.backend.saved_plan["SourceRealmSha256"] == "f" * 64
    assert any(c["Name"] == "Imported" for c in app.backend.saved_plan["Collections"])
    assert not app.workspace.dirty
    assert app.workspace.source_path.endswith("client.realm")


def test_gui_cancel_delete_and_save_preserve_staged_changes(app, monkeypatch, tmp_path):
    app.workspace = Workspace(DOCUMENT, "copied.realm")
    app.refresh_collections()
    monkeypatch.setattr(studio.messagebox, "askyesno", lambda *args, **kwargs: False)
    app.delete_collection()
    assert not app.workspace.dirty
    app.workspace.rename("one", "Renamed")
    monkeypatch.setattr(studio.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    app.save()
    assert app.workspace.dirty
    assert not app.backend.calls


def test_large_collection_paging_and_search_across_all_maps(app):
    hashes = [f"{index:032x}" for index in range(1201)]
    document = {
        "SourceRealmSha256": "f" * 64,
        "Collections": [{"Id": "large", "Name": "Large", "Hashes": hashes}],
    }
    app.workspace = Workspace(document, "copied.realm")
    app.refresh_collections()
    assert len(app.maps.get_children()) == 500
    app.select_all_maps()
    assert len(app.maps.selection()) == 500
    app.page_maps(1)
    assert len(app.maps.get_children()) == 500
    assert not app.maps.selection()
    app.page_maps(1)
    assert len(app.maps.get_children()) == 201
    app.map_search.set(hashes[0])
    assert len(app.maps.get_children()) == 1
    assert app.map_page == 0
    app.select_all_maps()
    app.remove_maps()
    assert app.workspace.collection("large")["Hashes"] == hashes[1:]


def test_download_window_updates_metadata_but_requires_client_import(app, tmp_path):
    from tools.download_window import DownloadWindow

    class Downloader:
        def run(self, hashes, directory, emit, stop):
            assert hashes == [B]
            details = {"Title": "Downloaded song", "Difficulty": "Extra"}
            emit({"kind": "metadata", "hash": B, "details": details})
            result = {
                "hash": B,
                "state": "Ready",
                "file": str(directory / "7.osz"),
                "details": details,
            }
            emit({"kind": "result", **result})
            return {"results": [result], "report_path": str(directory / "report.json")}

    app.workspace = Workspace(DOCUMENT, "copied.realm")
    app.refresh_collections()
    window = DownloadWindow(app, Downloader())
    window.directory.set(str(tmp_path))
    window.start()
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not window.running
    assert window.states[B]["state"] == "Ready"
    assert app.workspace.downloaded[B].endswith("7.osz")
    assert B not in app.workspace.present_hashes
    assert B in app.workspace.missing_hashes()
    assert not app.workspace.dirty
    window.close()


def test_stable_gui_open_rename_remove_save_and_reopen(app, monkeypatch, tmp_path):
    from tools.stable_collections import encode, read_stable

    source = tmp_path / "collection.db"
    original = encode([{"Name": "Stable", "Hashes": [A, B]}], version=20150203)
    source.write_bytes(original)
    app.load(str(source))
    finish(app)
    assert app.workspace.format == "stable"
    assert not app.backend.calls
    monkeypatch.setattr(studio.simpledialog, "askstring", lambda *args, **kwargs: "Renamed")
    app.rename_collection()
    app.root.update()
    app.maps.selection_set(app.maps.get_children()[0])
    app.remove_maps()
    monkeypatch.setattr(studio.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    app.save()
    finish(app)
    assert source.read_bytes() == original
    reopened = read_stable(app.workspace.source_path)
    assert reopened["Version"] == 20150203
    assert reopened["Collections"][0]["Name"] == "Renamed"
    assert reopened["Collections"][0]["Hashes"] == [B]


def test_gui_collector_import_merges_with_existing_collection_and_tracks_missing(app, monkeypatch):
    from tools import collector_import

    app.new_file()
    app.workspace.create("Remote")
    monkeypatch.setattr(studio.simpledialog, "askstring", lambda *args, **kwargs: "44")
    monkeypatch.setattr(
        collector_import,
        "fetch_collection",
        lambda value: {
            "Collections": [{"Name": "Remote", "Hashes": [A, A, B]}],
            "Beatmaps": {A: {"Title": "Remote song", "Available": False}},
            "Warnings": [],
        },
    )
    app.import_link()
    finish(app)
    app.import_link()
    finish(app)
    assert len(app.workspace.collections) == 1
    assert app.workspace.collections[0]["Hashes"] == [A, B]
    assert app.workspace.missing_hashes() == [A, B]
    assert app.last_import_ids == {app.workspace.collections[0]["Id"]}


def finish_migration(app, window):
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not window.running
    assert window.result is not None


def test_gui_migration_selects_collections_and_keeps_staged_edits(app, tmp_path):
    from tools.stable_collections import digest, read_stable

    source = tmp_path / "source.realm"
    source.write_bytes(b"Realm source fixture")
    document = {**DOCUMENT, "SourceRealmSha256": digest(source)}
    app.workspace = Workspace(document, str(source))
    app.workspace.rename("two", "練習 🎵 edited")
    app.refresh_collections()
    app.migrate_collections()
    window = app.migration_window
    assert set(window.groups.selection()) == {"one", "two"}
    assert window.to_stable
    assert window.target_entry.instate(["disabled"])
    window.none_button.invoke()
    app.root.update()
    assert window.start_button.instate(["disabled"])
    app.selected = "two"
    window.current_button.invoke()
    assert window.groups.selection() == ("two",)
    window.output_parent.set(str(tmp_path))
    window.start_button.invoke()
    finish_migration(app, window)
    result = window.result
    groups = read_stable(result["OutputFile"])["Collections"]
    assert [(group["Name"], group["Hashes"]) for group in groups] == [("練習 🎵 edited", [B])]
    assert result["IncludesUnsavedEdits"]
    assert result["SelectedCollections"] == 1
    assert app.workspace.dirty
    assert app.workspace.source_path == str(source)
    assert source.read_bytes() == b"Realm source fixture"
    assert not app.backend.calls
    window.close()
    assert app.migration_window is None


def test_gui_stable_to_realm_requires_target_and_publishes_new_copy(app, tmp_path):
    from tools.stable_collections import digest, encode, read_stable

    source = tmp_path / "collection.db"
    original = encode([{"Name": "Main", "Hashes": [A]}, {"Name": "Skip", "Hashes": [B]}])
    source.write_bytes(original)
    target = tmp_path / "copied.realm"
    target.write_bytes(b"Existing Realm fixture")

    class MergeBackend:
        def run(self, command, **options):
            assert command == "merge"
            groups = read_stable(options["collections"])["Collections"]
            assert [(group["Name"], group["Hashes"]) for group in groups] == [("Main", [A])]
            assert options["realm_copy"] == str(target)
            output = Path(options["output_directory"])
            output.mkdir()
            path = output / "client.realm"
            path.write_bytes(b"Merged fixture")
            return {
                "VerifiedAfterReopen": True,
                "SourceRealmSha256": digest(target),
                "OutputRealmSha256": digest(path),
                "Changes": [{"Action": "create", "AddedHashes": [A]}],
            }

    app.backend = MergeBackend()
    app.workspace = Workspace(read_stable(source), str(source))
    app.refresh_collections()
    app.migrate_collections()
    window = app.migration_window
    assert not window.to_stable
    assert window.target_entry.instate(["!disabled"])
    window.start()
    assert not window.running
    assert "destination database" in window.status.get()
    window.current_button.invoke()
    window.target.set(str(target))
    window.output_parent.set(str(tmp_path))
    window.start()
    finish_migration(app, window)
    assert window.result["Created"] == 1
    assert Path(window.result["OutputFile"]).read_bytes() == b"Merged fixture"
    assert target.read_bytes() == b"Existing Realm fixture"
    assert source.read_bytes() == original
    assert not app.workspace.dirty
    window.close()


def test_main_window_waits_for_migration_before_closing(app):
    app.workspace = Workspace(DOCUMENT, "copied.realm")
    app.refresh_collections()
    app.migrate_collections()
    window = app.migration_window
    window.running = True
    app.close()
    assert app.root.winfo_exists() and window.window.winfo_exists()
    assert "finish before closing" in window.status.get()
    window.running = False
    app.close()
    assert app.migration_window is None
    assert app.root.winfo_exists()


def test_gui_maps_link_import_preserves_existing_and_uses_remote_labels(app, monkeypatch):
    from tools import collection_links

    app.new_file()
    app.workspace.create("Keep existing")
    monkeypatch.setattr(studio.simpledialog, "askstring", lambda *args, **kwargs: "Maps link")
    monkeypatch.setattr(
        collection_links,
        "fetch_link",
        lambda value: {
            "SourceName": "Maps",
            "Collections": [{"Name": "Shared 練習", "Hashes": [A, A, B]}],
            "Beatmaps": {A: {"Title": "Shared song", "Available": False}},
            "Warnings": [],
        },
    )
    app.import_link()
    finish(app)
    app.import_link()
    finish(app)
    assert len(app.workspace.collections) == 2
    assert app.workspace.collection(app.selected)["Name"] == "Shared 練習"
    assert app.workspace.collection(app.selected)["Hashes"] == [A, B]
    assert app.workspace.beatmaps[A]["Title"] == "Shared song"
    assert A not in app.workspace.present_hashes
    assert app.status.get().startswith("Maps: 0 new collections, 0 added memberships.")
    app.undo()
    assert [group["Name"] for group in app.workspace.collections] == ["Keep existing"]


def test_download_window_can_run_with_only_hinamizawa_enabled(app, tmp_path):
    from tools.download_window import DownloadWindow

    class Downloader:
        def run(self, hashes, directory, emit, stop):
            assert hashes == [B]
            assert [mirror.name for mirror in self.mirrors] == ["Hinamizawa"]
            return {"report_path": str(directory / "report.json"), "results": [], "requested": 1}

    app.workspace = Workspace(DOCUMENT, "copied.realm")
    app.refresh_collections()
    window = DownloadWindow(app, downloader=Downloader())
    app.download_window = window
    assert len(window.mirror_flags) == 8
    for name, flag in window.mirror_flags.items():
        flag.set(name == "Nekoha")
    window.directory.set(str(tmp_path))
    window.start()
    assert not window.running
    assert "Hinamizawa" in window.status.get()
    window.mirror_flags["Nekoha"].set(False)
    window.mirror_flags["Hinamizawa"].set(True)
    window.start()
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not window.running and window.report_path == str(tmp_path / "report.json")
    window.close()


def test_resume_queue_restores_hashes_and_mirrors_after_reopening(app, monkeypatch, tmp_path):
    from tools.beatmap_downloads import QUEUE_FILE
    from tools.download_window import SAVED_SCOPE, DownloadWindow

    checksum_c = "c" * 32
    queue_path = tmp_path / QUEUE_FILE
    original = json.dumps(
        {"version": 1, "hashes": [A, B, checksum_c], "mirrors": ["Hinamizawa", "Nekoha"]}
    )
    queue_path.write_text(original)
    app.workspace = Workspace(DOCUMENT, "copied.realm")
    app.refresh_collections()
    previous = DownloadWindow(app)
    previous.close()
    app.download_directory = ""  # Also works without remembered in-memory settings.
    window = DownloadWindow(app)
    app.download_window = window
    monkeypatch.setattr(studio.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    window.resume_button.invoke()
    assert window.scope.get() == SAVED_SCOPE
    assert window.directory.get() == str(tmp_path)
    assert window.hashes == [B, checksum_c]  # Installed A is skipped; untouched C survives.
    assert window.start_button["text"] == "Resume remaining"
    assert {name for name, flag in window.mirror_flags.items() if flag.get()} == {
        "Hinamizawa",
        "Nekoha",
    }
    assert not app.workspace.dirty
    assert not app.workspace.downloaded  # Checkpoint alone never proves a download is valid.
    assert queue_path.read_text() == original
    window.close()


def test_cancelled_queue_can_resume_pending_rows_in_same_window(app, tmp_path):
    from tools.download_window import DownloadWindow

    class PausingDownloader:
        calls = 0

        def run(self, hashes, directory, emit, stop):
            self.calls += 1
            results = []
            if self.calls == 1:
                ready = {"hash": B, "state": "Ready", "file": "7.osz", "details": {}}
                emit({"kind": "result", **ready})
                results.append(ready)
                assert stop.wait(3)
            else:
                assert hashes == [B, "c" * 32]
                for checksum in hashes:
                    ready = {"hash": checksum, "state": "Ready", "file": "7.osz", "details": {}}
                    emit({"kind": "result", **ready})
                    results.append(ready)
            return {
                "results": results,
                "requested": len(hashes),
                "cancelled": stop.is_set(),
                "report_path": str(directory / "report.json"),
            }

    document = json.loads(json.dumps(DOCUMENT))
    document["Collections"][0]["Hashes"].append("c" * 32)
    app.workspace = Workspace(document, "copied.realm")
    app.refresh_collections()
    window = DownloadWindow(app, PausingDownloader())
    app.download_window = window
    window.directory.set(str(tmp_path))
    window.start()
    deadline = time.monotonic() + 3
    while B not in window.states and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert window.states[B]["state"] == "Ready"
    assert str(window.resume_button["state"]) == "disabled"
    window.cancel_button.invoke()
    while window.running and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not window.running
    assert "Paused" in window.status.get() and "1 remaining" in window.status.get()
    assert window.start_button["text"] == "Resume remaining"
    window.start_button.invoke()
    deadline = time.monotonic() + 3
    while window.running and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert not window.running
    assert all(window.states[value]["state"] == "Ready" for value in [B, "c" * 32])
    assert not app.workspace.dirty
    window.close()


def test_resume_missing_queue_keeps_current_selection(app, monkeypatch, tmp_path):
    from tools.download_window import DownloadWindow

    app.workspace = Workspace(DOCUMENT, "copied.realm")
    app.refresh_collections()
    window = DownloadWindow(app)
    monkeypatch.setattr(studio.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    window.resume_queue()
    assert "no saved download queue" in window.status.get()
    assert window.hashes == [B]
    assert not window.resume_mode
    window.close()


def test_classic_credits_viewer_opens_without_collection_and_reuses_window(app):
    app.show_credits()
    app.root.update()
    window = app.credits_window
    assert window.winfo_exists()
    assert "TheAussie" in app.credits_texts["Credits"].get("1.0", "end")
    assert "MIT License" in app.credits_texts["Project licence"].get("1.0", "end")
    assert "PySide6" in app.credits_texts["Third-party notices"].get("1.0", "end")
    assert app.workspace is None and not app.busy
    app.show_credits()
    assert app.credits_window is window
    window.destroy()
