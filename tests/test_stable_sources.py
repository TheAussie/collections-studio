import hashlib
import io
import json
import os
import struct

import pytest

from tools.collection_workspace import Workspace
from tools.collector_import import collection_id, fetch_collection
from tools.osu_database import read_osu_database
from tools.stable_collections import (
    decode,
    digest,
    encode,
    read_replay_cache,
    read_stable,
    save_stable,
    scan_songs,
)

A, B = "a" * 32, "b" * 32


def legacy_string(value):
    data = value.encode()
    result = bytearray([11])
    size = len(data)
    while size >= 128:
        result.append((size & 127) | 128)
        size >>= 7
    return bytes(result + bytes([size]) + data)


def osu_database(version=20260924, checksum=A):
    # Fixture independently follows ppy's documented database layout.
    entry = bytearray()
    for value in (
        "Artist",
        "歌手",
        "Title",
        "曲",
        "Mapper",
        "Hard",
        "audio.mp3",
        checksum,
        "map.osu",
    ):
        entry.extend(legacy_string(value))
    entry.extend(struct.pack("<BHHHq", 4, 10, 20, 1, 0))
    entry.extend(bytes(4) if version < 20140609 else struct.pack("<ffff", 9, 4, 5, 8))
    entry.extend(struct.pack("<d", 1.4))
    if version >= 20140609:
        for _ in range(4):
            entry.extend(struct.pack("<i", 1))
            entry.extend(b"\x08" + struct.pack("<i", 0))
            entry.extend(
                (b"\x0c" + struct.pack("<f", 5.2))
                if version >= 20250107
                else (b"\x0d" + struct.pack("<d", 5.2))
            )
    entry.extend(struct.pack("<iiii", 90, 100000, 1000, 1))
    entry.extend(struct.pack("<ddB", 180, 0, 1))
    entry.extend(struct.pack("<iiiBBBBhfB", 70, 7, 0, 0, 0, 0, 0, 0, 0.7, 0))
    entry.extend(legacy_string("source") + legacy_string("tags"))
    entry.extend(struct.pack("<h", 0) + legacy_string("font"))
    entry.extend(struct.pack("<BqB", 0, 0, 0) + legacy_string("7 Folder"))
    entry.extend(struct.pack("<qBBBBB", 0, 0, 0, 0, 0, 0))
    if version < 20140609:
        entry.extend(bytes(2))
    entry.extend(struct.pack("<iB", 0, 0))
    header = (
        struct.pack("<iiBq", version, 1, 1, 0)
        + legacy_string("Private user")
        + struct.pack("<i", 1)
    )
    if version < 20191106:
        entry = struct.pack("<i", len(entry)) + entry
    return header + entry + struct.pack("<i", 1)


@pytest.mark.parametrize("version", [20130101, 20150203, 20200101, 20250107, 20260924])
def test_osu_database_old_and_new_rating_layouts_read_without_rehashing(tmp_path, version):
    path = tmp_path / "osu!.db"
    path.write_bytes(osu_database(version))
    before = digest(path)
    document = read_osu_database(path)
    assert document["Version"] == version
    assert document["Scanned"] == 1
    assert document["Beatmaps"][A]["Title"] == "Title"
    assert document["Beatmaps"][A]["Difficulty"] == "Hard"
    assert document["Beatmaps"][A]["SetId"] == 7
    assert digest(path) == before


@pytest.mark.parametrize(
    "change", [lambda b: b[:-1], lambda b: b + b"extra", lambda b: b.replace(b"\x0c", b"\x0d", 1)]
)
def test_osu_database_refuses_bad_layout_without_partial_results(tmp_path, change):
    path = tmp_path / "osu!.db"
    path.write_bytes(change(osu_database()))
    with pytest.raises(ValueError):
        read_osu_database(path)


def test_stable_roundtrip_unicode_empty_and_source_version(tmp_path):
    groups = [{"Name": "練習 🎵" * 30, "Hashes": [A.upper(), B]}, {"Name": "Empty", "Hashes": []}]
    path = tmp_path / "collection.db"
    path.write_bytes(encode(groups, version=20150203))
    document = read_stable(path)
    assert document["Version"] == 20150203
    assert [(c["Name"], c["Hashes"]) for c in document["Collections"]] == [
        (c["Name"], c["Hashes"]) for c in groups
    ]
    workspace = Workspace(document, str(path))
    workspace.rename(workspace.collections[0]["Id"], "Renamed")
    original = path.read_bytes()
    report = save_stable(workspace, tmp_path / "export")
    assert path.read_bytes() == original
    assert report["VerifiedAfterReopen"]
    reopened = read_stable(report["OutputFile"])
    assert reopened["Collections"][0]["Name"] == "Renamed"
    assert reopened["Collections"][0]["Hashes"] == [A.upper(), B]
    assert reopened["Version"] == 20150203


def test_stable_save_empty_file_and_refuse_existing_output_or_stale_source(tmp_path):
    workspace = Workspace({"Format": "stable", "SourceRealmSha256": "", "Collections": []}, "")
    report = save_stable(workspace, tmp_path / "new")
    assert read_stable(report["OutputFile"])["Collections"] == []
    with pytest.raises(ValueError, match="already exists"):
        save_stable(workspace, tmp_path / "new")
    path = tmp_path / "source.db"
    path.write_bytes(encode([]))
    workspace = Workspace(read_stable(path), str(path))
    path.write_bytes(encode([{"Name": "Changed", "Hashes": [A]}]))
    with pytest.raises(ValueError, match="source changed"):
        save_stable(workspace, tmp_path / "stale")
    assert not (tmp_path / "stale").exists()


@pytest.mark.parametrize(
    "data", [b"", b"bad", encode([]) + b"extra", struct.pack("<ii", 20261026, -1)]
)
def test_stable_rejects_malformed_inputs(data):
    with pytest.raises(ValueError):
        decode(data)


def test_songs_cache_reuses_hashes_and_rehashes_changed_files(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    songs = tmp_path / "Songs"
    songs.mkdir()
    path = songs / "map.OSU"
    data = b"osu file format v14\nTitle:Song\nArtist:Artist\nVersion:Hard\n"
    path.write_bytes(data)
    original = hashlib.md5(data, usedforsecurity=False).hexdigest()
    first = scan_songs(songs)
    assert first["Hashed"] == 1 and first["Reused"] == 0
    second = scan_songs(songs)
    assert second["Hashed"] == 0 and second["Reused"] == 1
    assert original in second["Beatmaps"]
    path.write_bytes(data + b"Changed\n")
    assert scan_songs(songs)["Hashed"] == 1
    path.unlink()
    assert scan_songs(songs)["Stale"] == 1


def test_replay_parser_cache_contract_skips_stale_and_never_rehashes(tmp_path):
    path = tmp_path / "map.osu"
    path.write_bytes(b"file content need not be opened for a cache match")
    info = path.stat()
    cache = tmp_path / "beatmap-index-cache.json"
    cache.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": str(path),
                        "file_size": info.st_size,
                        "modified_timestamp": info.st_mtime_ns,
                        "md5": A,
                    },
                    {
                        "path": str(tmp_path / "missing.osu"),
                        "file_size": 1,
                        "modified_timestamp": 0,
                        "md5": B,
                    },
                ]
            }
        )
    )
    original = cache.read_bytes()
    result = read_replay_cache(cache)
    assert set(result["Beatmaps"]) == {A}
    assert result["ErrorCount"] == 1
    assert cache.read_bytes() == original
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
    assert not read_replay_cache(cache)["Beatmaps"]


class CollectorClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, url):
        self.calls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode())


def test_collector_keeps_original_md5s_unknown_hashes_and_deduplicates():
    client = CollectorClient(
        [
            {
                "name": "Practice",
                "beatmapCount": 3,
                "beatmapsets": [{"id": 7, "beatmaps": [{"checksum": A}, {"checksum": A.upper()}]}],
                "unknownChecksums": [B],
            },
            {
                "beatmaps": [
                    {"id": 70, "beatmapset_id": 7, "checksum": A, "version": "Hard"},
                    {"checksum": "c" * 32},
                ],
                "beatmapsets": [{"id": 7, "title": "Song"}],
            },
        ]
    )
    result = fetch_collection("https://osucollector.com/collections/44/practice", client)
    assert result["Collections"] == [{"Name": "Practice", "Hashes": [A, B]}]
    assert result["Beatmaps"][A]["Title"] == "Song"
    assert result["Beatmaps"][A]["Available"] is False
    assert "c" * 32 not in result["Beatmaps"]


def test_collector_metadata_failure_keeps_complete_collection():
    result = fetch_collection(
        "44",
        CollectorClient(
            [
                {
                    "name": "Practice",
                    "beatmapCount": 1,
                    "beatmapsets": [{"beatmaps": [{"checksum": A}]}],
                },
                OSError("metadata unavailable"),
            ]
        ),
    )
    assert result["Collections"][0]["Hashes"] == [A]
    assert result["Warnings"]


@pytest.mark.parametrize(
    "value",
    [
        "http://osucollector.com/collections/44",
        "https://evil.test/collections/44",
        "https://osucollector.com.evil.test/collections/44",
        "https://u:p@osucollector.com/collections/44",
        "0",
        "-2",
    ],
)
def test_collector_rejects_invalid_origins_before_fetch(value):
    with pytest.raises(ValueError):
        collection_id(value)


def test_collector_incomplete_or_invalid_checksum_response_is_not_imported():
    for document in [
        {"name": "Practice", "beatmapCount": 5, "beatmapsets": []},
        {
            "name": "Practice",
            "beatmapCount": 1,
            "beatmapsets": [{"beatmaps": [{"checksum": "bad"}]}],
        },
    ]:
        with pytest.raises(ValueError):
            fetch_collection("44", CollectorClient([document]))
