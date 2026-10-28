import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QFileDialog  # noqa: E402

from tests.qt_support import dispose  # noqa: E402
from tests.test_qt_studio import wait  # noqa: E402
from tests.test_qt_studio import window as window  # noqa: E402
from tests.test_stable_sources import osu_database  # noqa: E402
from tools.library_cache import library_key  # noqa: E402
from tools.qt_collection_studio import StudioWindow  # noqa: E402
from tools.stable_collections import encode  # noqa: E402


@pytest.mark.parametrize("inventory", ["scan", "osu_database", "neighbour"])
def test_new_window_restores_remembered_library_per_database(
    window, monkeypatch, tmp_path, qt_app, inventory
):
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        "tools.qt_collection_studio.QStandardPaths.writableLocation", lambda *_args: str(cache)
    )
    collections = tmp_path / "collection.db"
    original = encode([{"Name": "Empty", "Hashes": []}])
    collections.write_bytes(original)
    database = tmp_path / ("osu!.db" if inventory == "neighbour" else "separate.db")
    database.write_bytes(osu_database())
    window.load_path(str(collections))
    wait(window)
    if inventory == "scan":
        songs = tmp_path / "Songs"
        songs.mkdir()
        (songs / "map.osu").write_text(
            "osu file format v14\n[Metadata]\nTitle:Scanned fixture\nVersion:Extra\n"
        )
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(songs))
        window.scan_folder()
        wait(window)
    elif inventory == "osu_database":
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(database), ""))
        window.read_database()
        wait(window)
    expected = window.workspace.beatmaps.copy()
    binding = json.loads(window.settings.value(library_key(collections)))
    assert Path(binding["cache"]).is_file()
    assert not window.workspace.dirty and collections.read_bytes() == original
    window.settings.sync()
    if inventory != "scan":
        database.unlink()
    monkeypatch.setattr(
        "tools.osu_database.read_osu_database", lambda *_args: pytest.fail("Must reuse JSON")
    )
    restored = StudioWindow(
        settings=QSettings(window.settings.fileName(), QSettings.Format.IniFormat)
    )
    errors = []
    monkeypatch.setattr(restored, "error", errors.append)
    try:
        restored.load_path(str(collections))
        wait(restored)
        assert not errors and restored.workspace.beatmaps == expected
        assert "Restored saved" in restored.status.text()
        restored.browse_button.click()
        wait(restored)
        assert restored.map_model.rowCount() == 1
        other = tmp_path / "other.db"
        other.write_bytes(original)
        restored.load_path(str(other))
        wait(restored)
        assert not restored.workspace.library_hashes
    finally:
        restored.close()
        restored.pool.waitForDone(10000)
        qt_app.processEvents()
        dispose(restored)


def test_scanned_unsaved_database_remembers_inventory_after_save(window, monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        "tools.qt_collection_studio.QStandardPaths.writableLocation", lambda *_args: str(cache)
    )
    window.new_file()
    window.workspace.create("New")
    window.refresh_collections()
    database = tmp_path / "songs.db"
    database.write_bytes(osu_database())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(database), ""))
    window.read_database()
    wait(window)
    destination = tmp_path / "new collection.db"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *_args, **_kw: (str(destination), "")
    )
    window.save()
    wait(window)
    assert window.settings.value(library_key(destination))
    window.load_path(str(destination))
    wait(window)
    assert window.workspace.library_hashes == {"a" * 32}
    assert not window.errors


def test_save_copy_keeps_inventory_association_for_both_paths(window, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tools.qt_collection_studio.QStandardPaths.writableLocation",
        lambda *_args: str(tmp_path / "cache"),
    )
    source = tmp_path / "collection.db"
    source.write_bytes(encode([{"Name": "Test", "Hashes": []}]))
    database = tmp_path / "osu!.db"
    database.write_bytes(osu_database())
    window.load_path(str(source))
    wait(window)
    output = tmp_path / "exports"
    output.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(output))
    window.save_copy()
    wait(window)
    copy = window.workspace.source_path
    assert copy != str(source)
    assert window.settings.value(library_key(copy)) == window.settings.value(library_key(source))
    database.unlink()
    window.load_path(copy)
    wait(window)
    assert window.workspace.library_hashes == {"a" * 32}
    assert not window.errors
