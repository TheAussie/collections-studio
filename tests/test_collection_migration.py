import json
import os
from pathlib import Path

import pytest

from tools.collection_migration import capture_source, migrate
from tools.collection_workspace import Workspace
from tools.stable_collections import digest, encode, read_stable

A, B, C, D = (value * 32 for value in "abcd")


def realm_workspace(tmp_path):
    path = tmp_path / "source.realm"
    path.write_bytes(b"Read-only source fixture")
    return Workspace(
        {
            "SourceRealmSha256": digest(path),
            "Collections": [
                {"Id": "one", "Name": "Main", "Hashes": [A, B]},
                {"Id": "two", "Name": "練習 🎵", "Hashes": [B]},
                {"Id": "three", "Name": "Empty", "Hashes": []},
            ],
        },
        str(path),
    )


def contents(path):
    return {group["Name"]: group["Hashes"] for group in read_stable(path)["Collections"]}


def test_realm_export_includes_staged_edits_and_selected_empty_unicode_collections(tmp_path):
    workspace = realm_workspace(tmp_path)
    workspace.rename("two", "練習 🎵 revised")
    snapshot = capture_source(workspace, ["two", "three"])
    # Changes after capture cannot alter the detached migration plan.
    workspace.remove_maps("two", [B])
    report = migrate(snapshot, tmp_path / "export")
    assert contents(report["OutputFile"]) == {"練習 🎵 revised": [B], "Empty": []}
    assert report["SelectedCollections"] == 2
    assert report["IncludesUnsavedEdits"]
    assert report["Created"] == 2
    assert workspace.collection("two")["Hashes"] == []
    assert workspace.dirty
    assert digest(workspace.source_path) == workspace.source_hash
    if os.name == "posix":
        assert Path(report["OutputFile"]).stat().st_mode & 0o777 == 0o600
    assert json.loads(Path(report["ReportPath"]).read_text())["OutputFile"] == report["OutputFile"]


def test_realm_merges_stable_destination_exact_names_and_deduplicates_md5(tmp_path):
    workspace = realm_workspace(tmp_path)
    target = tmp_path / "existing.db"
    original = encode(
        [
            {"Name": "Main", "Hashes": [A.upper(), C]},
            {"Name": "Keep", "Hashes": [D]},
            {"Name": "main", "Hashes": [D]},
        ],
        20150203,
    )
    target.write_bytes(original)
    report = migrate(capture_source(workspace), tmp_path / "merged", target_path=target)
    assert contents(report["OutputFile"]) == {
        "Main": [A.upper(), C, B],
        "Keep": [D],
        "main": [D],
        "練習 🎵": [B],
        "Empty": [],
    }
    assert read_stable(report["OutputFile"])["Version"] == 20150203
    assert report["Created"] == 2 and report["Updated"] == 1
    assert report["AddedMemberships"] == 2
    assert target.read_bytes() == original
    assert not workspace.dirty


class RealmBackend:
    def __init__(self, hook=None, verified=True):
        self.hook = hook
        self.verified = verified

    def run(self, command, **options):
        assert command == "merge"
        self.incoming = contents(options["collections"])
        self.source = Path(options["realm_copy"])
        folder = Path(options["output_directory"])
        folder.mkdir()
        output = folder / "client.realm"
        output.write_bytes(b"Native result fixture")
        result = {
            "SourceRealmSha256": digest(self.source),
            "OutputRealm": str(output),
            "OutputRealmSha256": digest(output),
            "VerifiedAfterReopen": self.verified,
            "Changes": [{"Action": "merge", "AddedHashes": [B]}],
        }
        (folder / "import-report.json").write_text(json.dumps(result))
        if self.hook:
            self.hook()
        return result


def test_stable_to_realm_passes_only_selected_collections_to_native_union(tmp_path):
    source = tmp_path / "collection.db"
    source.write_bytes(
        encode([{"Name": "Main", "Hashes": [A, B]}, {"Name": "Skip", "Hashes": [C]}])
    )
    original = source.read_bytes()
    workspace = Workspace(read_stable(source), str(source))
    target = tmp_path / "target.realm"
    target.write_bytes(b"Existing Realm fixture")
    backend = RealmBackend()
    report = migrate(
        capture_source(workspace, [workspace.collections[0]["Id"]]),
        tmp_path / "realm-export",
        backend=backend,
        target_path=target,
    )
    assert backend.incoming == {"Main": [A, B]}
    assert target.read_bytes() == b"Existing Realm fixture"
    assert source.read_bytes() == original
    assert report["Updated"] == 1 and report["Created"] == 0
    assert report["DestinationFormat"] == "realm"
    assert report["VerifiedAfterReopen"]
    rewritten = json.loads((Path(report["OutputFile"]).parent / "import-report.json").read_text())
    assert rewritten["OutputRealm"] == report["OutputFile"]
    assert not list(tmp_path.glob(".collections-migration-*"))


def test_failed_native_verification_publishes_no_output(tmp_path):
    workspace = realm_workspace(tmp_path)
    workspace.format = "stable"
    target = tmp_path / "target.realm"
    target.write_bytes(b"Realm fixture")
    with pytest.raises(ValueError, match="reopening"):
        migrate(
            capture_source(workspace),
            tmp_path / "rejected",
            target_path=target,
            backend=RealmBackend(verified=False),
        )
    assert not (tmp_path / "rejected").exists()
    assert not list(tmp_path.glob(".collections-migration-*"))


@pytest.mark.parametrize("changed", ["source", "target"])
def test_source_or_destination_changed_during_work_publishes_nothing(tmp_path, changed):
    workspace = realm_workspace(tmp_path)
    workspace.format = "stable"
    target = tmp_path / "target.realm"
    target.write_bytes(b"Realm fixture")
    path = Path(workspace.source_path) if changed == "source" else target
    with pytest.raises(ValueError, match="changed"):
        migrate(
            capture_source(workspace),
            tmp_path / "rejected",
            target_path=target,
            backend=RealmBackend(hook=lambda: path.write_bytes(b"Externally changed")),
        )
    assert not (tmp_path / "rejected").exists()


def test_stale_selection_source_and_existing_output_are_rejected(tmp_path):
    workspace = realm_workspace(tmp_path)
    with pytest.raises(ValueError, match="at least one"):
        capture_source(workspace, [])
    with pytest.raises(ValueError, match="selected collections changed"):
        capture_source(workspace, ["unknown"])
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        migrate(capture_source(workspace), output)
    Path(workspace.source_path).write_bytes(b"Changed")
    with pytest.raises(ValueError, match="source file changed"):
        migrate(capture_source(workspace), tmp_path / "stale")
    assert not (tmp_path / "stale").exists()


def test_ambiguous_existing_stable_names_leave_target_and_output_untouched(tmp_path):
    workspace = realm_workspace(tmp_path)
    target = tmp_path / "ambiguous.db"
    original = encode([{"Name": "Main", "Hashes": [C]}, {"Name": "Main", "Hashes": [D]}])
    target.write_bytes(original)
    with pytest.raises(ValueError, match="More than one"):
        migrate(capture_source(workspace), tmp_path / "rejected", target_path=target)
    assert target.read_bytes() == original
    assert not (tmp_path / "rejected").exists()


def test_stable_migration_requires_existing_realm_copy_and_normalizes_duplicate_incoming(tmp_path):
    workspace = realm_workspace(tmp_path)
    workspace.format = "stable"
    with pytest.raises(ValueError, match="existing copied"):
        migrate(capture_source(workspace), tmp_path / "no-target")
    workspace.format = "realm"
    workspace.collections[0]["Hashes"] = [A, A.upper(), B, B]
    report = migrate(capture_source(workspace, ["one"]), tmp_path / "dedup")
    assert contents(report["OutputFile"]) == {"Main": [A, B]}
