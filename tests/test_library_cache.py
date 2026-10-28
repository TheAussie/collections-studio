import json
import os
import threading

import pytest

from tests.test_stable_sources import osu_database
from tools.beatmap_downloads import Cancelled
from tools.collection_application import load_document
from tools.library_cache import cache_database_inventory, restore_library
from tools.osu_database import read_osu_database
from tools.stable_collections import encode, scan_songs

A, B = "a" * 32, "b" * 32


def test_osu_inventory_json_reused_and_restored_without_original_database(tmp_path, monkeypatch):
    source = tmp_path / "osu!.db"
    original = osu_database()
    source.write_bytes(original)
    document = read_osu_database(source)
    binding = cache_database_inventory(source, document, tmp_path / "cache")
    cache = tmp_path / "cache" / os.path.basename(binding["cache"])
    assert "Private user" not in cache.read_text()
    saved = cache.read_bytes()
    future = cache.stat().st_mtime_ns + 20_000_000_000
    os.utime(cache, ns=(future, future))
    assert cache_database_inventory(source, document, tmp_path / "cache") == binding
    assert cache.read_bytes() == saved and cache.stat().st_mtime_ns == future
    assert len(list(cache.parent.glob("*.json"))) == 1
    assert source.read_bytes() == original
    source.unlink()
    collections = tmp_path / "collection.db"
    collections.write_bytes(encode([{"Name": "Test", "Hashes": [A]}]))
    monkeypatch.setattr(
        "tools.osu_database.read_osu_database", lambda *_args: pytest.fail("Must use saved JSON")
    )
    result = load_document(collections, None, library_source=binding)
    assert result["Beatmaps"] == document["Beatmaps"]
    assert "unavailable" in result["LibraryNotice"]


def test_neighbour_osu_database_cached_then_skipped_even_if_changed(tmp_path, monkeypatch):
    source = tmp_path / "osu!.db"
    source.write_bytes(osu_database())
    collections = tmp_path / "collection.db"
    collections.write_bytes(encode([{"Name": "Test", "Hashes": [A]}]))
    result = load_document(collections, None, cache_directory=tmp_path / "cache")
    binding = result["LibrarySource"]
    source.write_bytes(osu_database(checksum=B))
    stamp = binding["mtime_ns"] + 2_000_000_000
    os.utime(source, ns=(stamp, stamp))
    monkeypatch.setattr(
        "tools.osu_database.read_osu_database", lambda *_args: pytest.fail("No database reread")
    )
    restored = load_document(collections, None, library_source=binding)
    assert set(restored["Beatmaps"]) == {A}
    assert "has changed" in restored["LibraryNotice"]


def test_scan_restore_keeps_labels_skips_stale_files_and_never_walks_or_rehashes(
    tmp_path, monkeypatch
):
    songs = tmp_path / "Songs"
    songs.mkdir()
    for name in ["one", "two", "three"]:
        (songs / f"{name}.osu").write_text(
            f"osu file format v14\n[Metadata]\nTitle:{name}\nArtist:Fixture\nVersion:Extra\n"
        )
    scanned = scan_songs(songs, cache_directory=tmp_path / "cache")
    binding = scanned["LibrarySource"]
    (songs / "two.osu").unlink()
    (songs / "three.osu").write_text("changed .osu bytes")
    monkeypatch.setattr(os, "walk", lambda *_args, **_kw: pytest.fail("Must not rescan"))
    restored = restore_library(binding)
    assert restored["Scanned"] == 1 and restored["ErrorCount"] == 2
    assert next(iter(restored["Beatmaps"].values()))["Title"] == "one"
    assert next(iter(restored["Beatmaps"].values()))["Difficulty"] == "Extra"
    assert "2 changed/missing" in restored["LibraryNotice"]


def test_identical_scan_keeps_newer_json_bytes_timestamp_and_entry_order(tmp_path):
    songs = tmp_path / "Songs"
    songs.mkdir()
    for name in ["one", "two"]:
        (songs / f"{name}.osu").write_text(f"osu file format v14\n[Metadata]\nTitle:{name}\n")
    result = scan_songs(songs, cache_directory=tmp_path / "cache")
    cache = next((tmp_path / "cache").glob("*.json"))
    data = json.loads(cache.read_text())
    data["entries"].reverse()
    cache.write_text(json.dumps(data))
    before = cache.read_bytes()
    future = cache.stat().st_mtime_ns + 20_000_000_000
    os.utime(cache, ns=(future, future))
    assert scan_songs(songs, cache_directory=tmp_path / "cache")["Reused"] == 2
    assert cache.read_bytes() == before and cache.stat().st_mtime_ns == future
    assert restore_library(result["LibrarySource"])["Scanned"] == 2
    (songs / "one.osu").write_text("osu file format v14\n[Metadata]\nTitle:Updated\n")
    scan_songs(songs, cache_directory=tmp_path / "cache")
    assert len(list(cache.parent.glob("*.json"))) == 1
    assert cache.read_bytes() != before


@pytest.mark.parametrize("failure", ["missing", "corrupt", "wrong_schema"])
def test_bad_saved_inventory_never_prevents_collection_open(tmp_path, failure):
    source = tmp_path / "osu!.db"
    source.write_bytes(osu_database())
    binding = cache_database_inventory(source, read_osu_database(source), tmp_path / "cache")
    cache = next((tmp_path / "cache").glob("*.json"))
    if failure == "missing":
        cache.unlink()
    else:
        cache.write_text("{" if failure == "corrupt" else '{"version":999}')
    source.unlink()
    collections = tmp_path / "collection.db"
    collections.write_bytes(encode([{"Name": "Test", "Hashes": [A]}]))
    result = load_document(collections, None, library_source=binding)
    assert result["Collections"][0]["Hashes"] == [A]
    assert "could not be restored" in result["LibraryError"]


def test_empty_and_cancelled_saved_scan_are_safe(tmp_path):
    songs = tmp_path / "Songs"
    songs.mkdir()
    scanned = scan_songs(songs, cache_directory=tmp_path / "cache")
    assert restore_library(scanned["LibrarySource"])["Scanned"] == 0
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        restore_library(scanned["LibrarySource"], stop=stop)
