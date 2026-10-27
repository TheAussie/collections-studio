"""Copy collection memberships between formats; publish only verified new files."""

import hashlib
import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from tools.beatmap_downloads import _private_json
from tools.collection_workspace import Workspace
from tools.stable_collections import DEFAULT_VERSION, digest, encode, read_stable, save_stable


def capture_source(workspace, collection_ids=None):
    identifiers = {group["Id"] for group in workspace.collections}
    selected = identifiers if collection_ids is None else set(collection_ids)
    if not selected:
        raise ValueError("Select at least one collection to migrate.")
    if selected - identifiers:
        raise ValueError("The selected collections changed. Open migration again.")
    groups = [
        {"Name": group["Name"], "Hashes": deepcopy(group["Hashes"])}
        for group in workspace.collections
        if group["Id"] in selected
    ]
    return {
        "Format": workspace.format,
        "Path": workspace.source_path,
        "Sha256": workspace.source_hash,
        "Collections": groups,
        "UnsavedEdits": workspace.dirty,
    }


def _check_source(source):
    if source["Path"] and digest(source["Path"]) != source["Sha256"]:
        raise ValueError("The source file changed since opening. Reopen it before migrating.")


def _publish(prepared, output, names):
    for name in names:
        path = prepared / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Migration output is incomplete. No result was published.")
    output.mkdir(mode=0o700)  # Exclusive creation; never replace even an empty directory.
    linked = []
    try:
        for name in names:
            destination = output / name
            os.link(prepared / name, destination)
            linked.append(destination)
    except Exception:
        for path in linked:
            path.unlink()
        output.rmdir()
        raise


def migrate(source, directory, *, backend=None, target_path=""):
    """Realm -> new/merged stable file, or stable -> a supplied Realm copy.

    `source` is a detached snapshot from capture_source, including staged edits.
    Existing destination collections merge by exact name and case-insensitive MD5.
    """
    if source["Format"] not in ("realm", "stable"):
        raise ValueError("Unsupported source collection format.")
    if not source["Collections"]:
        raise ValueError("Select at least one collection to migrate.")
    destination_format = "stable" if source["Format"] == "realm" else "realm"
    requested = Path(directory).expanduser()
    output = requested.parent.resolve() / requested.name
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists. Choose a new folder.")
    if not output.parent.is_dir():
        raise ValueError("The output parent folder must already exist.")
    if destination_format == "realm" and (not target_path or backend is None):
        raise ValueError("Select an existing copied client.realm as the destination.")
    _check_source(source)
    incoming = encode(source["Collections"], DEFAULT_VERSION)
    target = str(Path(target_path).expanduser().resolve()) if target_path else ""
    work = Path(tempfile.mkdtemp(prefix=".collections-migration-", dir=output.parent))
    try:
        prepared = work / "result"
        if destination_format == "stable":
            document = (
                read_stable(target)
                if target
                else {
                    "Format": "stable",
                    "Version": DEFAULT_VERSION,
                    "SourceRealmSha256": "",
                    "Collections": [],
                }
            )
            destination = Workspace(document, target)
            created, added = destination.merge(source["Collections"])
            updated = destination.summary()[1]
            report = save_stable(destination, prepared)
            filename, hash_key = "collection.db", "OutputSha256"
            report["OutputFile"] = str(output / filename)
            target_hash = report["SourceSha256"]
            counts = {"Created": created, "Updated": updated, "AddedMemberships": added}
        else:
            legacy = work / "incoming.db"
            with legacy.open("xb") as stream:
                legacy.chmod(0o600)
                stream.write(incoming)
            report = backend.run(
                "merge", collections=legacy, realm_copy=target, output_directory=prepared
            )
            filename, hash_key = "client.realm", "OutputRealmSha256"
            report["OutputRealm"] = str(output / filename)
            target_hash = report["SourceRealmSha256"]
            changes = report["Changes"]
            counts = {
                "Created": sum(change["Action"] == "create" for change in changes),
                "Updated": sum(change["Action"] == "merge" for change in changes),
                "AddedMemberships": sum(len(change["AddedHashes"]) for change in changes),
            }
        if not report.get("VerifiedAfterReopen"):
            raise ValueError("The migrated file did not pass reopening verification.")
        _check_source(source)
        if target and digest(target) != target_hash:
            raise ValueError("The destination source file changed. No result was published.")
        if digest(prepared / filename) != report[hash_key]:
            raise ValueError("The prepared output changed. No result was published.")
        _private_json(prepared / "import-report.json", report)
        migration = {
            "SourceFormat": source["Format"],
            "SourceFile": source["Path"],
            "SourceSha256": source["Sha256"],
            "IncludesUnsavedEdits": source["UnsavedEdits"],
            "DestinationFormat": destination_format,
            "DestinationSource": target,
            "DestinationSourceSha256": target_hash,
            "SelectedCollections": len(source["Collections"]),
            "SelectedMemberships": sum(len(group["Hashes"]) for group in source["Collections"]),
            "SelectedContentsSha256": hashlib.sha256(incoming).hexdigest(),
            "CollectionNames": [group["Name"] for group in source["Collections"]],
            "OutputFile": str(output / filename),
            "OutputSha256": report[hash_key],
            "VerifiedAfterReopen": True,
            **counts,
        }
        _private_json(prepared / "migration-report.json", migration)
        _publish(prepared, output, (filename, "import-report.json", "migration-report.json"))
        return {**migration, "ReportPath": str(output / "migration-report.json")}
    finally:
        shutil.rmtree(work)
