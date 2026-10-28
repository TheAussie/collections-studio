"""Owner-local inventory snapshots; collection databases never contain cache settings."""

import hashlib
import json
from pathlib import Path

from tools.beatmap_downloads import _check_cancel, _private_json, valid_hash

MAX_CACHE = 128 * 1024 * 1024


def read_cache_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_CACHE + 1)
    if len(data) > MAX_CACHE:
        raise ValueError("Saved song library exceeds 128 MiB. Refresh the inventory.")
    return json.loads(data)


def write_cache_json(path, document, *, entries=False):
    """Reuse identical contents, including a newer cache's bytes and timestamp."""
    path = Path(path)
    try:
        old = read_cache_json(path)
        same = old == document
        if entries and isinstance(old, dict):
            before, after = old["entries"], document["entries"]
            same = len(before) == len(after) and {entry["path"]: entry for entry in before} == {
                entry["path"]: entry for entry in after
            }
        if same:
            return
    except (ValueError, OSError, TypeError, KeyError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private_json(path, document)


def library_key(database_path):
    return (
        "song-libraries/" + hashlib.sha256(str(Path(database_path).resolve()).encode()).hexdigest()
    )


def cache_database_inventory(source, document, cache_directory):
    source = Path(source).resolve()
    key = hashlib.sha256(str(source).encode()).hexdigest()[:20]
    path = Path(cache_directory) / f"osu-inventory-{key}.json"
    info = source.stat()
    write_cache_json(
        path,
        {"version": 1, "source": str(source), "Beatmaps": document["Beatmaps"]},
    )
    return {
        "kind": "osu_database",
        "source": str(source),
        "cache": str(path),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def restore_library(source, *, stop=None, progress=None):
    if stop is not None:
        _check_cancel(stop)
    if not isinstance(source, dict) or not isinstance(source.get("cache"), str):
        raise ValueError("Saved song library setting is invalid. Choose the inventory again.")
    if source.get("kind") == "scan":
        from tools.stable_collections import read_replay_cache

        document = read_replay_cache(
            source["cache"], stop=stop, progress=progress, allow_empty=True
        )
        notice = f"Restored saved Songs scan: {document['Scanned']:,} maps. " + (
            f"{document['ErrorCount']:,} changed/missing files skipped; scan Songs to refresh."
            if document["ErrorCount"]
            else "Scan Songs to find newly added files."
        )
    elif source.get("kind") == "osu_database":
        cached = read_cache_json(source["cache"])
        if (
            not isinstance(cached, dict)
            or cached.get("version") != 1
            or cached.get("source") != source.get("source")
            or not isinstance(cached.get("Beatmaps"), dict)
            or any(
                not valid_hash(checksum) or not isinstance(details, dict)
                for checksum, details in cached["Beatmaps"].items()
            )
        ):
            raise ValueError("Saved osu!.db inventory is invalid. Read osu!.db again to refresh.")
        maps = cached["Beatmaps"]
        document = {"Beatmaps": maps, "Scanned": len(maps), "ErrorCount": 0}
        notice = f"Restored saved osu!.db inventory: {len(maps):,} maps."
        try:
            info = Path(source["source"]).stat()
            if (info.st_size, info.st_mtime_ns) != (source.get("size"), source.get("mtime_ns")):
                notice += " osu!.db has changed; read it again to refresh the saved library."
        except OSError:
            notice += " Original osu!.db is unavailable; using its saved library."
    else:
        raise ValueError("Saved song library type is unsupported. Choose the inventory again.")
    if stop is not None:
        _check_cancel(stop)
    return {**document, "LibrarySource": source, "LibraryNotice": notice}
