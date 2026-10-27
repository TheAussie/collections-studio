from copy import deepcopy

import pytest

from tools.collection_workspace import Workspace

A, B, C = (value * 32 for value in "abc")


@pytest.fixture
def document():
    return {
        "SourceRealmSha256": "f" * 64,
        "Collections": [
            {"Id": "one", "Name": "Main", "Hashes": [A, B]},
            {"Id": "two", "Name": "Shared", "Hashes": [B]},
        ],
        "Beatmaps": {A: {"Title": "Song", "Artist": "Artist", "Difficulty": "Hard"}},
    }


def test_edit_membership_and_undo_preserve_other_collections(document):
    original = deepcopy(document)
    workspace = Workspace(document, "source.realm")
    workspace.remove_maps("one", [B.upper()])
    assert workspace.collection("one")["Hashes"] == [A]
    assert workspace.collection("two")["Hashes"] == [B]
    assert workspace.summary() == (0, 1, 0)
    assert document == original
    workspace.undo()
    assert not workspace.dirty


def test_merge_is_union_idempotent_and_single_undo(document):
    workspace = Workspace(document, "source.realm")
    incoming = [
        {"Name": "Main", "Hashes": [B.upper(), C, C]},
        {"Name": "練習 🎵", "Hashes": [B]},
        {"Name": "Empty", "Hashes": []},
        {"Name": "main", "Hashes": [A]},
    ]
    assert workspace.merge(incoming) == (3, 3)
    assert workspace.collection("one")["Hashes"] == [A, B, C]
    assert len(workspace.collections) == 5
    assert workspace.merge(incoming) == (0, 0)
    workspace.undo()
    assert not workspace.dirty
    assert not workspace.can_undo


def test_import_failure_is_atomic(document):
    document["Collections"].append({"Id": "three", "Name": "Main", "Hashes": []})
    workspace = Workspace(document, "source.realm")
    with pytest.raises(ValueError, match="More than one"):
        workspace.merge([{"Name": "New", "Hashes": [C]}, {"Name": "Main", "Hashes": [C]}])
    assert not workspace.dirty
    assert len(workspace.collections) == 3
    assert not workspace.can_undo


def test_rename_create_delete_and_save_baseline(document):
    workspace = Workspace(document, "source.realm")
    workspace.rename("one", "日本語 🎵")
    created = workspace.create("New")
    workspace.delete("two")
    assert workspace.summary() == (1, 1, 1)
    plan = workspace.plan()
    plan["Collections"].clear()
    assert len(workspace.collections) == 2
    workspace.mark_saved("new.realm", "e" * 64)
    assert workspace.source_path == "new.realm"
    assert workspace.plan()["SourceRealmSha256"] == "e" * 64
    assert workspace.collection(created)["Hashes"] == []
    assert not workspace.dirty
    assert not workspace.can_undo


@pytest.mark.parametrize("name", ["", "   ", "bad\x00name", "Shared"])
def test_invalid_or_duplicate_name_leaves_workspace_unchanged(document, name):
    workspace = Workspace(document, "source.realm")
    with pytest.raises(ValueError):
        workspace.rename("one", name)
    assert not workspace.dirty
    assert not workspace.can_undo


def test_noop_changes_do_not_create_undo_entries(document):
    workspace = Workspace(document, "source.realm")
    workspace.rename("one", "Main")
    workspace.remove_maps("one", [C])
    assert not workspace.can_undo
    workspace.delete("one")
    assert workspace.beatmaps == document["Beatmaps"]
    assert workspace.collection("two")["Hashes"] == [B]


def test_missing_hashes_deduplicate_and_do_not_treat_remote_metadata_as_installed(document):
    workspace = Workspace(document, "source.realm")
    assert workspace.missing_hashes() == [B]
    workspace.beatmaps[B] = {"Title": "Looked up remotely"}
    workspace.downloaded[B] = "7.osz"
    assert workspace.missing_hashes({"two"}) == [B]
    document["Beatmaps"][A]["Available"] = False
    workspace = Workspace(document, "source.realm")
    assert workspace.missing_hashes() == [A, B]
