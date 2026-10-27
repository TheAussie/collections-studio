"""Standalone stable collection.db editing with read-only inputs and new outputs."""

import hashlib
import json
import os
import shutil
import struct
import tempfile
from pathlib import Path
from uuid import uuid4

from tools.beatmap_downloads import MAX_OSU, _check_cancel, _private_json, valid_hash

MAX_BYTES = 32 * 1024 * 1024
DEFAULT_VERSION = 20261026


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def decode(data):
    if len(data) > MAX_BYTES:
        raise ValueError("collection.db exceeds 32 MiB.")
    position = 0

    def take(size):
        nonlocal position
        if size < 0 or position + size > len(data):
            raise ValueError("collection.db is truncated.")
        value = data[position : position + size]
        position += size
        return value

    def number(limit):
        (value,) = struct.unpack("<i", take(4))
        if not 0 <= value <= limit:
            raise ValueError("Invalid collection.db count or version.")
        return value

    def string():
        marker = take(1)[0]
        if marker == 0:
            return ""
        if marker != 11:
            raise ValueError("Invalid collection.db string marker.")
        length = 0
        for shift in range(0, 35, 7):
            next_byte = take(1)[0]
            if shift == 28 and next_byte > 15:
                raise ValueError("Invalid collection.db string length.")
            length |= (next_byte & 127) << shift
            if next_byte < 128:
                break
        else:
            raise ValueError("Invalid collection.db string length.")
        if length > 1024 * 1024:
            raise ValueError("A collection.db string exceeds 1 MiB.")
        try:
            return take(length).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 in collection.db.") from error

    version = number(2**31 - 1)
    collections, total = [], 0
    for _ in range(number(10_000)):
        name = string()
        count = number(1_000_000)
        total += count
        if total > 1_000_000:
            raise ValueError("Too many collection memberships.")
        hashes = [string() for _ in range(count)]
        if not all(valid_hash(checksum) for checksum in hashes):
            raise ValueError("A difficulty has an invalid MD5 checksum.")
        collections.append({"Id": str(uuid4()), "Name": name, "Hashes": hashes})
    if position != len(data):
        raise ValueError("Unexpected trailing bytes in collection.db.")
    return {
        "Version": version,
        "Collections": collections,
        "Format": "stable",
        "SourceRealmSha256": hashlib.sha256(data).hexdigest(),
    }


def read_stable(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("collection.db exceeds 32 MiB.")
        stream.seek(0)
        if hashlib.file_digest(stream, "sha256").hexdigest() != hashlib.sha256(data).hexdigest():
            raise ValueError("collection.db changed while reading. Try opening it again.")
    return decode(data)


def encode(collections, version=DEFAULT_VERSION):
    output = bytearray(struct.pack("<ii", version, len(collections)))

    def string(value):
        data = value.encode("utf-8")
        if not data:
            output.append(0)
            return
        if len(data) > 1024 * 1024:
            raise ValueError("A collection name exceeds 1 MiB.")
        output.append(11)
        length = len(data)
        while length >= 128:
            output.append((length & 127) | 128)
            length >>= 7
        output.append(length)
        output.extend(data)

    if len(collections) > 10_000 or sum(len(c["Hashes"]) for c in collections) > 1_000_000:
        raise ValueError("Too many collections or memberships.")
    for collection in collections:
        string(collection["Name"])
        output.extend(struct.pack("<i", len(collection["Hashes"])))
        for checksum in collection["Hashes"]:
            if not valid_hash(checksum):
                raise ValueError("A difficulty has an invalid MD5 checksum.")
            string(checksum)
        if len(output) > MAX_BYTES:
            raise ValueError("collection.db exceeds 32 MiB.")
    return bytes(output)


def save_stable(workspace, directory):
    output = Path(directory).resolve()
    if output.exists():
        raise ValueError("Output already exists. Choose a new directory.")
    if workspace.source_path and digest(workspace.source_path) != workspace.source_hash:
        raise ValueError("The source changed since opening. Reopen it before saving.")
    data = encode(workspace.collections, workspace.legacy_version)
    expected = [(c["Name"], c["Hashes"]) for c in workspace.collections]
    decoded = decode(data)
    if expected != [(c["Name"], c["Hashes"]) for c in decoded["Collections"]]:
        raise ValueError("collection.db verification failed.")
    temporary = Path(tempfile.mkdtemp(prefix=".collections-export-", dir=output.parent))
    try:
        file = temporary / "collection.db"
        with file.open("xb") as stream:
            file.chmod(0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if encode(read_stable(file)["Collections"], workspace.legacy_version) != data:
            raise ValueError("Saved collection.db failed verification.")
        if workspace.source_path and digest(workspace.source_path) != workspace.source_hash:
            raise ValueError("The source changed during save. No output was published.")
        report = {
            "Format": "stable",
            "SourceSha256": workspace.source_hash,
            "OutputFile": str(output / "collection.db"),
            "OutputSha256": hashlib.sha256(data).hexdigest(),
            "Collections": len(workspace.collections),
            "VerifiedAfterReopen": True,
            "Changes": dict(
                zip(("created", "edited", "deleted"), workspace.summary(), strict=True)
            ),
        }
        _private_json(temporary / "import-report.json", report)
        output.mkdir(mode=0o700)
        try:
            os.link(file, output / "collection.db")
            os.link(temporary / "import-report.json", output / "import-report.json")
        except Exception:
            (output / "collection.db").unlink(missing_ok=True)
            (output / "import-report.json").unlink(missing_ok=True)
            output.rmdir()
            raise
        return report
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def scan_songs(folder, *, stop=None, progress=None, cache_directory=None):
    """Hash only .osu files, leaving Songs and its archives untouched."""
    folder = Path(folder).resolve()
    if cache_directory is None:
        base = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            if os.name == "nt"
            else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        )
        cache_root = base / "collections-studio"
    else:
        cache_root = Path(cache_directory)
    cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_path = cache_root / (hashlib.sha256(str(folder).encode()).hexdigest()[:20] + ".json")
    cached = _cache_entries(cache_path)
    maps, errors, scanned, reused, entries = {}, [], 0, 0, []
    for directory, _children, files in os.walk(folder, followlinks=False):
        for name in files:
            if stop is not None:
                _check_cancel(stop)
            if progress is not None and scanned % 100 == 0:
                progress(f"Scanning Songs: {scanned:,} beatmaps checked")
            path = Path(directory) / name
            if path.suffix.lower() != ".osu":
                continue
            try:
                info = path.stat()
                old = cached.pop(str(path), None)
                if (
                    old
                    and old.get("file_size") == info.st_size
                    and old.get("modified_timestamp") == info.st_mtime_ns
                ):
                    checksum = old["md5"].lower()
                    metadata = old.get("metadata")
                    maps[checksum] = (
                        metadata
                        if isinstance(metadata, dict)
                        else {"Title": path.stem, "Available": True}
                    )
                    entries.append(old)
                    scanned += 1
                    reused += 1
                    continue
                if info.st_size > MAX_OSU:
                    raise ValueError(".osu file exceeds 32 MiB")
                with path.open("rb") as stream:
                    prefix = stream.read(65536)
                    stream.seek(0)
                    checksum = hashlib.file_digest(stream, "md5").hexdigest()
                text = prefix.decode("utf-8-sig", errors="replace")
                if not text.lstrip().startswith("osu file format v"):
                    raise ValueError("invalid .osu header")
                fields = {}
                for line in text.splitlines():
                    key, separator, value = line.partition(":")
                    if separator:
                        fields.setdefault(key.strip(), value.strip())
                maps[checksum] = {
                    "Title": fields.get("Title", ""),
                    "Artist": fields.get("Artist", ""),
                    "Difficulty": fields.get("Version", ""),
                    "Available": True,
                    "Mode": {"0": "osu", "1": "taiko", "2": "fruits", "3": "mania"}.get(
                        fields.get("Mode", "0"), ""
                    ),
                }
                scanned += 1
                entries.append(
                    {
                        "path": str(path),
                        "file_size": info.st_size,
                        "modified_timestamp": info.st_mtime_ns,
                        "md5": checksum,
                        "metadata": maps[checksum],
                    }
                )
            except (OSError, ValueError) as error:
                errors.append(str(path) + ": " + str(error))
    if stop is not None:
        _check_cancel(stop)
    _private_json(cache_path, {"entries": entries})
    return {
        "Beatmaps": maps,
        "Scanned": scanned,
        "Errors": errors[:20],
        "ErrorCount": len(errors),
        "Reused": reused,
        "Hashed": scanned - reused,
        "Stale": len(cached),
    }


def _cache_entries(path):
    try:
        if not Path(path).is_file() or Path(path).stat().st_size > 128 * 1024 * 1024:
            return {}
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            entry["path"]: entry
            for entry in document["entries"]
            if isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and valid_hash(entry.get("md5"))
        }
    except (ValueError, OSError, TypeError, KeyError):
        return {}


def read_replay_cache(path):
    """Replay Parser's path + file_size + modified_timestamp(ns) cache contract."""
    entries = _cache_entries(path)
    if not entries:
        raise ValueError("No readable beatmap-index-cache.json entries were found.")
    maps, stale = {}, 0
    for filename, entry in entries.items():
        file = Path(filename)
        try:
            info = file.stat()
            if (
                file.suffix.lower() != ".osu"
                or info.st_size != entry.get("file_size")
                or info.st_mtime_ns != entry.get("modified_timestamp")
            ):
                stale += 1
                continue
        except OSError:
            stale += 1
            continue
        maps[entry["md5"].lower()] = {"Title": file.stem, "Available": True}
    return {"Beatmaps": maps, "Scanned": len(maps), "ErrorCount": stale}
