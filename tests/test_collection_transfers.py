from copy import deepcopy

import pytest

from tools.collection_workspace import Workspace
from tools.stable_collections import decode, encode

A, B, C, D = (value * 32 for value in "abcd")


def workspace(format="stable"):
    return Workspace(
        {
            "Format": format,
            "Version": 20250107,
            "SourceRealmSha256": "f" * 64,
            "Collections": [
                {"Id": "source", "Name": "Source 練習", "Hashes": [A.upper(), A, B, C]},
                {"Id": "target", "Name": "Target", "Hashes": [B.upper()]},
                {"Id": "other", "Name": "Untouched", "Hashes": [A]},
            ],
            "Beatmaps": {
                A: {"Title": "Local", "Available": True},
                D: {"Title": "Indexed missing", "Available": False},
            },
        },
        "copied source.realm" if format == "realm" else "source collection.db",
    )


@pytest.mark.parametrize("format", ["stable", "realm"])
def test_copy_merges_by_md5_preserves_source_and_undoes_once(format):
    work = workspace(format)
    before, metadata = deepcopy(work.collections), deepcopy(work.beatmaps)
    report = work.transfer_maps("source", "target", [A.upper(), A, B])
    assert report == {"selected": 2, "added": 1, "already_present": 1, "removed": 0}
    assert work.collection("target")["Hashes"] == [B.upper(), A]
    assert work.collection("source") == before[0] and work.collection("other") == before[2]
    assert work.beatmaps == metadata and work.source_hash == "f" * 64
    assert work.transfer_maps("source", "target", [A, B])["added"] == 0
    work.undo()
    assert work.collections == before and not work.can_undo and not work.dirty


@pytest.mark.parametrize("format", ["stable", "realm"])
def test_move_already_present_hash_never_loses_destination_and_is_atomic_undo(format):
    work = workspace(format)
    before = deepcopy(work.collections)
    report = work.transfer_maps("source", "target", [A, A.upper(), B], move=True)
    assert report == {"selected": 2, "added": 1, "already_present": 1, "removed": 2}
    assert work.collection("source")["Hashes"] == [C]
    assert work.collection("target")["Hashes"] == [B.upper(), A]
    assert work.collection("other") == before[2]
    if format == "stable":
        output = decode(encode(work.collections, work.legacy_version))
        assert output["Version"] == 20250107
        assert output["Collections"][1]["Hashes"] == [B.upper(), A]
    after = deepcopy(work.collections)
    with pytest.raises(ValueError, match="source collection"):
        work.transfer_maps("source", "target", [A], move=True)
    assert work.collections == after
    work.undo()
    assert work.collections == before and not work.can_undo


def test_same_collection_and_copying_existing_membership_are_noops():
    work = workspace()
    assert work.transfer_maps("source", "source", [A], move=True)["removed"] == 0
    assert work.transfer_maps("source", "target", [B])["added"] == 0
    assert not work.dirty and not work.can_undo


@pytest.mark.parametrize("hashes", [[], ["invalid"], [A, D], [A, None]])
def test_invalid_or_stale_selection_is_rejected_without_partial_edits(hashes):
    work = workspace()
    before = deepcopy(work.collections)
    with pytest.raises(ValueError):
        work.transfer_maps("source", "target", hashes, move=True)
    assert work.collections == before and not work.can_undo
    with pytest.raises(ValueError, match="collection changed"):
        work.transfer_maps("source", "missing", [A], move=True)
    assert work.collections == before


def test_preexisting_legacy_duplicates_are_preserved_but_never_added_again():
    work = workspace()
    work.collection("target")["Hashes"] = [B, B.upper()]
    before = deepcopy(work.collections)
    report = work.transfer_maps("source", "target", [B, B.upper(), C])
    assert report["already_present"] == 1 and report["added"] == 1
    assert work.collection("target")["Hashes"] == [B, B.upper(), C]
    work.undo()
    assert work.collections == before


def test_game_inventory_is_separate_from_imported_remote_metadata():
    work = workspace()
    assert work.library_hashes == {A}
    work.beatmaps[C] = {"Title": "Remote import", "Available": False}
    with pytest.raises(ValueError, match="game library"):
        work.add_library_maps("target", [A, C])
    assert not work.dirty
    work.load_inventory({"Beatmaps": {C.upper(): {"Title": "Installed", "Available": True}}})
    assert work.library_hashes == work.present_hashes == {C}
    report = work.add_library_maps("target", [C, C.upper()])
    assert report["selected"] == report["added"] == 1
    assert work.add_library_maps("target", [C])["already_present"] == 1
    work.undo()
    assert not work.dirty and not work.can_undo
    assert work.library_hashes == {C}  # Undo changes memberships, not the inventory.


def test_realm_lists_all_indexed_hashes_and_duplicate_inventory_prefers_available():
    work = workspace("realm")
    assert work.library_hashes == {A, D} and work.present_hashes == {A}
    work.load_inventory(
        {
            "Beatmaps": {
                C: {"Title": "Installed", "Available": True},
                C.upper(): {"Title": "Stale duplicate", "Available": False},
            }
        }
    )
    assert work.beatmaps[C]["Title"] == "Installed"
    assert work.present_hashes == {A, C}
    assert work.add_library_maps("target", [D])["added"] == 1
