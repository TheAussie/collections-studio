import os
from copy import deepcopy
from pathlib import Path

import pytest

from tools import collection_exports as exports
from tools.collection_workspace import Workspace
from tools.stable_collections import DEFAULT_VERSION, digest, encode, read_stable

A, B, C = (value * 32 for value in "abc")


@pytest.fixture(params=["stable", "realm"])
def workspace(tmp_path, request):
    groups = [
        {"Id": "one", "Name": "Main", "Hashes": [A, A.upper(), B]},
        {"Id": "two", "Name": "練習 🎵", "Hashes": [B, C]},
        {"Id": "empty", "Name": "Empty", "Hashes": []},
    ]
    source = tmp_path / ("collection.db" if request.param == "stable" else "client.realm")
    source.write_bytes(
        encode(groups, 20150203) if request.param == "stable" else b"Synthetic Realm source"
    )
    return Workspace(
        {
            "Format": request.param,
            "Version": 20150203,
            "SourceRealmSha256": digest(source),
            "Collections": groups,
        },
        str(source),
    )


def contents(path):
    return [(group["Name"], group["Hashes"]) for group in read_stable(path)["Collections"]]


def test_selected_export_preserves_unsaved_unicode_empty_and_detached_memberships(
    workspace, tmp_path
):
    workspace.rename("two", "練習 🎵 edited")
    snapshot = exports.capture_export(workspace, {"two", "empty"})
    workspace.remove_maps("two", [B])
    before = deepcopy(vars(workspace))
    original = Path(workspace.source_path).read_bytes()
    folder = tmp_path / "export 練習"
    folder.mkdir()
    result = exports.export_collection_file(snapshot, folder / "collection.db")
    assert contents(result["OutputFile"]) == [("練習 🎵 edited", [B, C]), ("Empty", [])]
    assert result["Collections"] == 2 and result["Memberships"] == 2
    assert result["IncludesUnsavedEdits"] and result["VerifiedAfterReopen"]
    assert digest(result["OutputFile"]) == result["OutputSha256"]
    expected_version = 20150203 if workspace.format == "stable" else DEFAULT_VERSION
    assert read_stable(result["OutputFile"])["Version"] == expected_version
    assert vars(workspace) == before
    assert Path(workspace.source_path).read_bytes() == original
    assert [p.name for p in folder.iterdir()] == ["collection.db"]


def test_all_export_keeps_collection_order_names_case_and_existing_duplicate_entries(
    workspace, tmp_path
):
    workspace.collections[1]["Name"] = "Main"  # Legacy duplicate names stay distinct.
    snapshot = exports.capture_export(workspace)
    result = exports.export_collection_file(snapshot, tmp_path / "full.db")
    assert contents(result["OutputFile"]) == [
        ("Main", [A, A.upper(), B]),
        ("Main", [B, C]),
        ("Empty", []),
    ]
    assert result["Collections"] == 3 and result["Memberships"] == 5


@pytest.mark.parametrize("selection", [set(), {"unknown"}])
def test_empty_or_stale_selection_is_rejected(workspace, selection):
    with pytest.raises(ValueError):
        exports.capture_export(workspace, selection)


def test_export_never_overwrites_existing_destination_or_source(workspace, tmp_path):
    snapshot = exports.capture_export(workspace)
    target = tmp_path / "existing.db"
    target.write_bytes(b"Keep existing output")
    with pytest.raises(FileExistsError):
        exports.export_collection_file(snapshot, target)
    assert target.read_bytes() == b"Keep existing output"
    source = Path(workspace.source_path)
    original = source.read_bytes()
    with pytest.raises(FileExistsError):
        exports.export_collection_file(snapshot, source)
    assert source.read_bytes() == original
    source.unlink()
    with pytest.raises(ValueError, match="opened database"):
        exports.export_collection_file(snapshot, source)
    assert not source.exists()


def test_export_uses_working_snapshot_without_modifying_an_externally_changed_source(
    workspace, tmp_path
):
    snapshot = exports.capture_export(workspace)
    source = Path(workspace.source_path)
    source.write_bytes(b"External writer changed the opened source")
    result = exports.export_collection_file(snapshot, tmp_path / "export.db")
    assert contents(result["OutputFile"])[0] == ("Main", [A, A.upper(), B])
    assert source.read_bytes() == b"External writer changed the opened source"


def test_publication_race_preserves_the_other_writer_and_cleans_private_staging(
    workspace, tmp_path, monkeypatch
):
    target = tmp_path / "export.db"
    original_link = exports.os.link

    def race(source, destination):
        target.write_bytes(b"Other writer's file")
        return original_link(source, destination)

    monkeypatch.setattr(exports.os, "link", race)
    with pytest.raises(FileExistsError):
        exports.export_collection_file(exports.capture_export(workspace), target)
    assert target.read_bytes() == b"Other writer's file"
    assert not list(tmp_path.glob(".collections-export-*"))


def test_failed_verification_leaves_no_output(workspace, tmp_path, monkeypatch):
    target = tmp_path / "export.db"
    monkeypatch.setattr(exports, "read_stable", lambda _path: {"Version": 0, "Collections": []})
    with pytest.raises(ValueError, match="verification"):
        exports.export_collection_file(exports.capture_export(workspace), target)
    assert not target.exists() and not list(tmp_path.glob(".collections-export-*"))


def test_post_publication_sync_warning_does_not_discard_verified_export(
    workspace, tmp_path, monkeypatch
):
    def fail(_path):
        raise OSError("Synthetic sync failure")

    monkeypatch.setattr(exports, "_sync_directory", fail)
    result = exports.export_collection_file(
        exports.capture_export(workspace), tmp_path / "export.db"
    )
    assert result["Warnings"] and result["VerifiedAfterReopen"]
    assert contents(result["OutputFile"])[-1] == ("Empty", [])


def test_dangling_destination_symlink_is_not_followed(workspace, tmp_path):
    if os.name == "nt":
        pytest.skip("Creating symbolic links may require Windows developer mode")
    target, other = tmp_path / "export.db", tmp_path / "missing.db"
    target.symlink_to(other)
    with pytest.raises(FileExistsError):
        exports.export_collection_file(exports.capture_export(workspace), target)
    assert target.is_symlink() and not other.exists()


def test_unsupported_publication_leaves_no_partial_file(workspace, tmp_path, monkeypatch):
    def fail(*_args):
        raise OSError("Synthetic filesystem without hard-link support")

    monkeypatch.setattr(exports.os, "link", fail)
    target = tmp_path / "export.db"
    with pytest.raises(OSError):
        exports.export_collection_file(exports.capture_export(workspace), target)
    assert not target.exists() and not list(tmp_path.glob(".collections-export-*"))
