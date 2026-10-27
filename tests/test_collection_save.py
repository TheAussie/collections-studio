import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import collection_save
from tools.collection_save import database_save_lock, save_open_workspace
from tools.collection_workspace import Workspace
from tools.stable_collections import digest, encode, read_stable


@pytest.fixture
def opened(tmp_path):
    folder = tmp_path / "database with spaces 練習"
    folder.mkdir()
    path = folder / "collection.db"
    original = encode([{"Name": "Main", "Hashes": ["a" * 32]}], 20150203)
    path.write_bytes(original)
    workspace = Workspace(read_stable(path), str(path))
    workspace.rename(workspace.collections[0]["Id"], "Edited 練習 🎵")
    return workspace, path, original


def test_save_keeps_open_path_and_creates_a_distinct_byte_exact_backup_every_time(opened):
    workspace, path, original = opened
    first = save_open_workspace(workspace, None)
    assert first["OutputFile"] == str(path) and first["SaveState"] == "saved"
    assert first["BackupSha256"] == workspace.source_hash
    backup = Path(first["BackupFile"])
    assert backup.parent == path.parent and backup.read_bytes() == original
    assert read_stable(path)["Version"] == 20150203
    assert read_stable(path)["Collections"][0]["Name"] == "Edited 練習 🎵"
    assert json.loads(Path(first["ReportPath"]).read_text())["SaveState"] == "saved"
    previous = path.read_bytes()
    workspace.mark_saved(first["OutputFile"], first["OutputSha256"])
    workspace.rename(workspace.collections[0]["Id"], "Second save")
    second = save_open_workspace(workspace, None)
    assert Path(second["BackupFile"]).read_bytes() == previous
    assert second["BackupFile"] != first["BackupFile"] and backup.read_bytes() == original
    assert not list(path.parent.glob(".collections-save-*"))


def test_backup_failure_never_replaces_the_open_file(opened, monkeypatch):
    workspace, path, original = opened

    def fail(*_args):
        raise PermissionError("No space for backup")

    monkeypatch.setattr(collection_save, "_backup", fail)
    with pytest.raises(PermissionError, match="backup"):
        save_open_workspace(workspace, None)
    assert path.read_bytes() == original and workspace.dirty
    assert not list(path.parent.glob("*.save-report-*.json"))


def test_failed_publication_retains_original_and_verified_backup(opened, monkeypatch):
    workspace, path, original = opened
    replace = collection_save.os.replace

    def deny(source, destination):
        if Path(destination) == path:
            raise PermissionError("Locked target")
        return replace(source, destination)

    monkeypatch.setattr(collection_save.os, "replace", deny)
    with pytest.raises(OSError, match="backup is at"):
        save_open_workspace(workspace, None)
    assert workspace.dirty and path.read_bytes() == original
    assert next(path.parent.glob("*.backup-*.db")).read_bytes() == original
    report = json.loads(next(path.parent.glob("*.save-report-*.json")).read_text())
    assert report["SaveState"] == "prepared"


@pytest.mark.parametrize("phase", ["before", "during_stage", "after_backup"])
def test_externally_changed_source_is_never_overwritten(opened, monkeypatch, phase):
    workspace, path, original = opened
    changed = encode([{"Name": "Someone else's edit", "Hashes": []}])
    if phase == "before":
        path.write_bytes(changed)
    elif phase == "during_stage":
        original_save = collection_save.save_workspace

        def change(*args):
            result = original_save(*args)
            path.write_bytes(changed)
            return result

        monkeypatch.setattr(collection_save, "save_workspace", change)
    else:
        original_backup = collection_save._backup

        def change(*args):
            original_backup(*args)
            path.write_bytes(changed)

        monkeypatch.setattr(collection_save, "_backup", change)
    with pytest.raises(ValueError, match="source changed"):
        save_open_workspace(workspace, None)
    assert path.read_bytes() == changed and workspace.dirty
    backups = list(path.parent.glob("*.backup-*.db"))
    assert len(backups) == (1 if phase == "after_backup" else 0)
    if backups:
        assert backups[0].read_bytes() == original


def test_corrupt_backup_is_rejected_and_removed_before_replacement(opened, monkeypatch):
    workspace, path, original = opened
    original_digest = collection_save.digest
    monkeypatch.setattr(
        collection_save,
        "digest",
        lambda file: "0" * 64 if ".backup-" in str(file) else original_digest(file),
    )
    with pytest.raises(ValueError, match="backup did not match"):
        save_open_workspace(workspace, None)
    assert path.read_bytes() == original and not list(path.parent.glob("*.backup-*"))


def test_previous_backup_collision_never_overwrites_it(opened, monkeypatch):
    workspace, path, original = opened
    monkeypatch.setattr(
        collection_save,
        "datetime",
        SimpleNamespace(now=lambda _zone: datetime(2026, 10, 26, tzinfo=UTC)),
    )
    monkeypatch.setattr(collection_save, "uuid4", lambda: SimpleNamespace(hex="abcd" * 8))
    first = save_open_workspace(workspace, None)
    workspace.mark_saved(str(path), digest(path))
    previous = path.read_bytes()
    workspace.rename(workspace.collections[0]["Id"], "Another edit")
    with pytest.raises(FileExistsError):
        save_open_workspace(workspace, None)
    assert path.read_bytes() == previous and Path(first["BackupFile"]).read_bytes() == original


def test_final_report_failure_reports_saved_state_instead_of_a_false_failed_save(
    opened, monkeypatch
):
    workspace, path, original = opened
    original_json = collection_save._private_json

    def fail_final(path, report):
        if report["SaveState"] == "saved":
            raise PermissionError("Report write failed")
        return original_json(path, report)

    monkeypatch.setattr(collection_save, "_private_json", fail_final)
    report = save_open_workspace(workspace, None)
    assert report["SaveState"] == "saved" and report["Warnings"]
    assert Path(report["BackupFile"]).read_bytes() == original
    assert digest(path) == report["OutputSha256"]


def test_new_file_never_replaces_an_existing_destination(opened):
    old, path, original = opened
    workspace = Workspace({"Format": "stable", "SourceRealmSha256": "", "Collections": []}, "")
    with pytest.raises(ValueError, match="destination already exists"):
        save_open_workspace(workspace, None, new_path=path)
    assert path.read_bytes() == original
    target = path.parent / "New file 練習.db"
    report = save_open_workspace(workspace, None, new_path=target)
    assert report["BackupFile"] is None and read_stable(target)["Collections"] == []
    assert old.dirty


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink fixture")
def test_save_refuses_a_source_replaced_by_a_symlink(opened):
    workspace, path, original = opened
    target = path.with_name("other.db")
    target.write_bytes(original)
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError, match="link"):
        save_open_workspace(workspace, None)
    assert path.is_symlink() and target.read_bytes() == original


@pytest.mark.skipif(
    sys.platform == "win32", reason="Native Windows lock acceptance remains pending"
)
def test_held_realm_shared_lock_refuses_save_before_backup(opened):
    import fcntl

    workspace, path, original = opened
    workspace.format = "realm"
    lock = Path(str(path) + ".lock")
    lock.write_bytes(b"Realm coordination bytes")
    with lock.open("r+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(PermissionError, match="database is in use"):
            save_open_workspace(workspace, None)
    assert path.read_bytes() == original
    assert lock.read_bytes() == b"Realm coordination bytes"
    assert not list(path.parent.glob("*.backup-*"))
    with database_save_lock(path, realm=True):
        with pytest.raises(PermissionError):
            with database_save_lock(path, realm=True):
                pytest.fail("Two saves must not acquire the same lock")
