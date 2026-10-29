"""Export a detached working-session selection to one new, verified collection.db."""

import hashlib
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from tools.collection_save import _sync_directory
from tools.stable_collections import DEFAULT_VERSION, encode, read_stable


def capture_export(workspace, collection_ids=None):
    available = {group["Id"] for group in workspace.collections}
    selected = available if collection_ids is None else set(collection_ids)
    if not selected:
        raise ValueError("Choose at least one collection to export.")
    if selected - available:
        raise ValueError("The selected collections changed. Open Export again.")
    return {
        "SourcePath": workspace.source_path,
        "Version": workspace.legacy_version if workspace.format == "stable" else DEFAULT_VERSION,
        "IncludesUnsavedEdits": workspace.dirty,
        "Collections": [
            {"Name": group["Name"], "Hashes": deepcopy(group["Hashes"])}
            for group in workspace.collections
            if group["Id"] in selected
        ],
    }


def export_collection_file(snapshot, filename):
    """Verify before atomic no-overwrite publication; never reopen or edit the source."""
    requested = Path(filename).expanduser()
    target = requested.parent.resolve() / requested.name
    if not target.parent.is_dir():
        raise ValueError("Choose an existing folder for the export.")
    if target.exists() or target.is_symlink():
        raise FileExistsError("That file already exists. Choose a new export filename or folder.")
    if snapshot["SourcePath"] and target == Path(snapshot["SourcePath"]).expanduser().resolve():
        raise ValueError("Choose a different filename from the opened database.")
    groups = snapshot["Collections"]
    if not groups:
        raise ValueError("Choose at least one collection to export.")
    version = snapshot["Version"]
    data = encode(groups, version)
    expected = [(group["Name"], group["Hashes"]) for group in groups]
    checksum = hashlib.sha256(data).hexdigest()
    warnings = []
    with tempfile.TemporaryDirectory(
        prefix=".collections-export-", dir=target.parent, ignore_cleanup_errors=True
    ) as folder:
        prepared = Path(folder) / "collection.db"
        with prepared.open("xb") as stream:
            prepared.chmod(0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        verified = read_stable(prepared)
        actual = [(group["Name"], group["Hashes"]) for group in verified["Collections"]]
        if verified["Version"] != version or actual != expected:
            raise ValueError("The exported collection.db failed verification.")
        # Same-filesystem hard-link creation is atomic and refuses an existing
        # destination, including one created while this export was being verified.
        os.link(prepared, target)
        try:
            _sync_directory(target.parent)
        except OSError:
            warnings.append("The export was written, but the final folder sync failed.")
    return {
        "OutputFile": str(target),
        "OutputSha256": checksum,
        "Collections": len(groups),
        "Memberships": sum(len(group["Hashes"]) for group in groups),
        "IncludesUnsavedEdits": snapshot["IncludesUnsavedEdits"],
        "VerifiedAfterReopen": True,
        "Warnings": warnings,
    }
