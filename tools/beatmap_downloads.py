"""Sequential mirror fallback with exact .osu MD5 verification; no Realm writes."""

import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import zlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath

USER_AGENT = "CollectionsStudio/1.0 (osu collection manager)"
CHUNK = 128 * 1024
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_OSU = 32 * 1024 * 1024
MAX_JSON = 8 * 1024 * 1024
QUEUE_FILE = ".collections-download-queue.json"
INDEX_FILE = ".collections-downloads.json"
MAX_QUEUE = 32 * 1024 * 1024


def report_directory():
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "CollectionsStudio" / "download-reports"


def download_counts(hashes, states):
    ready = sum(states.get(h, {}).get("state") == "Ready" for h in hashes)
    failed = sum(states.get(h, {}).get("state") == "Failed" for h in hashes)
    installed = sum(
        states.get(h, {}).get("state") == "Ready" and states[h].get("installed", False)
        for h in hashes
    )
    return ready, len(hashes) - ready - failed, failed, installed


def _write_report(document, folder=None):
    folder = report_directory() if folder is None else Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"download-report-{uuid.uuid4().hex[:12]}.json"
    _private_json(path, document)
    reports = sorted(
        (p for p in folder.glob("download-report-*.json") if p.is_file() and not p.is_symlink()),
        key=lambda p: (p == path, p.stat().st_mtime_ns),
        reverse=True,
    )
    for old in reports[10:]:
        if old != path:
            try:
                old.unlink()
            except OSError:
                pass
    return path


class Cancelled(Exception):
    pass


class DownloadError(Exception):
    pass


@dataclass(frozen=True)
class Mirror:
    name: str
    download: str
    lookup: str = ""
    dialect: str = ""


MIRRORS = (
    Mirror(
        "osu.direct",
        "https://osu.direct/api/d/{id}",
        "https://osu.direct/api/v2/md5/{md5}/set",
        "set",
    ),
    Mirror(
        "Mirria",
        "https://mirror.lisek.cc/d/{id}",
        "https://mirror.lisek.cc/api/v1/beatmaps/md5/{md5}",
        "set",
    ),
    Mirror("Nerinyan", "https://api.nerinyan.moe/d/{id}"),
    Mirror("Sayobot", "https://dl.sayobot.cn/beatmaps/download/full/{id}"),
    Mirror("Nekoha", "https://mirror.nekoha.moe/api/download/{id}"),
    Mirror("Beatconnect", "https://beatconnect.io/b/{id}/"),
    Mirror("osu!dl", "https://osudl.org/s/{id}"),
    Mirror(
        "Hinamizawa",
        "https://mirror.hinamizawa.ai/api/v1/hinai/d/{id}",
        "https://mirror.hinamizawa.ai/api/md5/{md5}/set",
        "cheesegull-set",
    ),
)


def valid_hash(value):
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def checked_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise DownloadError("A mirror returned an invalid HTTPS URL.")
    if parsed.hostname in ("localhost", "localhost.localdomain"):
        raise DownloadError("A mirror redirected to a local address.")
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            raise DownloadError("A mirror redirected to a private address.")
    except ValueError:
        pass
    return url


class HttpsRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return super().redirect_request(
            request, response, code, message, headers, checked_url(new_url)
        )


class HttpClient:
    def __init__(self):
        self.opener = urllib.request.build_opener(HttpsRedirects())

    def open(self, url):
        return self.opener.open(
            urllib.request.Request(
                checked_url(url),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity",
                },
            ),
            timeout=15,
        )


def positive_id(value):
    try:
        result = int(value)
        return result if result > 0 and not isinstance(value, bool) else None
    except (ValueError, TypeError, OverflowError):
        return None


def resolve_response(mirror, document, requested):
    """A resolver must explicitly return the requested checksum, never just a set ID."""
    if not isinstance(document, dict):
        raise DownloadError("The lookup response is not a beatmap object.")
    if mirror.dialect in ("cheesegull", "cheesegull-set"):
        group = document
        if mirror.dialect == "cheesegull-set":
            children = group.get("ChildrenBeatmaps")
            if not isinstance(children, list):
                raise DownloadError("The lookup response has no difficulty list.")
            document = next(
                (
                    child
                    for child in children
                    if isinstance(child, dict)
                    and str(child.get("FileMD5", "")).lower() == requested
                ),
                None,
            )
            if document is None:
                raise DownloadError("The lookup returned no exact MD5 match.")
            if positive_id(group.get("SetID")) != positive_id(document.get("ParentSetID")):
                raise DownloadError("The lookup returned inconsistent beatmapset IDs.")
        if str(document.get("FileMD5", "")).lower() != requested:
            raise DownloadError("The lookup returned a different MD5.")
        set_id = positive_id(document.get("ParentSetID"))
        details = {
            "Title": group.get("Title", ""),
            "Artist": group.get("Artist", ""),
            "Difficulty": document.get("DiffName", ""),
            "BeatmapId": positive_id(document.get("BeatmapID")),
            "Mode": mode_name(document.get("Mode")),
        }
    else:
        maps = document.get("beatmaps", [])
        if not isinstance(maps, list):
            raise DownloadError("The lookup response has no beatmap list.")
        match = next(
            (
                item
                for item in maps
                if isinstance(item, dict) and str(item.get("checksum", "")).lower() == requested
            ),
            None,
        )
        if not match:
            raise DownloadError("The lookup returned no exact MD5 match.")
        set_id = positive_id(document.get("id"))
        details = {
            "Title": document.get("title", ""),
            "Artist": document.get("artist", ""),
            "Difficulty": match.get("version", ""),
            "BeatmapId": positive_id(match.get("id")),
            "Mode": mode_name(match.get("mode_int", match.get("mode"))),
        }
    if not set_id:
        raise DownloadError("The lookup returned no valid beatmapset ID.")
    return set_id, details


def mode_name(value):
    text = str(value) if isinstance(value, (str, int)) else ""
    return {"0": "osu", "1": "taiko", "2": "fruits", "3": "mania"}.get(text, text)


def _check_cancel(stop):
    if stop.is_set():
        raise Cancelled()


def inspect_archive(path, stop=None):
    """Read all ZIP members for CRC checks; hash original .osu bytes without extracting."""
    stop = stop or threading.Event()
    if Path(path).stat().st_size > MAX_ARCHIVE:
        raise DownloadError("The archive exceeds 512 MiB.")
    maps = {}
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 20_000 or sum(m.file_size for m in members) > MAX_EXPANDED:
                raise DownloadError("The archive exceeds the expanded size or entry limit.")
            expanded = 0
            for member in members:
                _check_cancel(stop)
                name = PurePosixPath(member.filename.replace("\\", "/"))
                if name.is_absolute() or ".." in name.parts or ":" in member.filename:
                    raise DownloadError("The archive contains an unsafe filename.")
                if stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
                    raise DownloadError("Encrypted archives and symlinks are unsupported.")
                if member.is_dir():
                    continue
                is_map = name.suffix.lower() == ".osu"
                if is_map and member.file_size > MAX_OSU:
                    raise DownloadError("A .osu file exceeds 32 MiB.")
                checksum = hashlib.md5(usedforsecurity=False) if is_map else None
                prefix = bytearray()
                size = 0
                with archive.open(member) as stream:
                    while data := stream.read(CHUNK):
                        _check_cancel(stop)
                        size += len(data)
                        expanded += len(data)
                        if expanded > MAX_EXPANDED or size > member.file_size:
                            raise DownloadError("The archive expands beyond its declared size.")
                        if is_map:
                            checksum.update(data)
                            if len(prefix) < 65536:
                                prefix.extend(data[: 65536 - len(prefix)])
                if is_map:
                    text = bytes(prefix).decode("utf-8-sig", errors="replace")
                    if not text.lstrip().startswith("osu file format v"):
                        raise DownloadError("An archive .osu entry has an invalid header.")
                    fields = {}
                    for line in text.splitlines():
                        key, separator, value = line.partition(":")
                        if separator and key.strip() in {
                            "Title",
                            "Artist",
                            "Version",
                            "Mode",
                            "BeatmapID",
                            "BeatmapSetID",
                        }:
                            fields.setdefault(key.strip(), value.strip())
                    maps[checksum.hexdigest()] = {
                        "Title": fields.get("Title", ""),
                        "Artist": fields.get("Artist", ""),
                        "Difficulty": fields.get("Version", ""),
                        "Mode": mode_name(positive_id(fields.get("Mode")) or 0),
                        "BeatmapId": positive_id(fields.get("BeatmapID")),
                        "SetId": positive_id(fields.get("BeatmapSetID")),
                    }
    except (zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError, zlib.error) as error:
        raise DownloadError("Invalid or corrupt .osz archive: " + str(error)) from error
    if not maps:
        raise DownloadError("The download contains no .osu difficulties.")
    return maps


def _private_json(path, document):
    handle, temporary = tempfile.mkstemp(prefix=".collections-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_download_queue(directory):
    """Restore requested hashes; completion records are loaded separately."""
    path = Path(directory) / QUEUE_FILE
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("The queue must be an ordinary file.")
        with path.open("rb") as stream:
            data = stream.read(MAX_QUEUE + 1)
        if len(data) > MAX_QUEUE:
            raise ValueError("The queue exceeds 32 MiB.")
        document = json.loads(data)
        if (
            not isinstance(document, dict)
            or type(document.get("version")) is not int
            or document["version"] != 1
            or not isinstance(document.get("hashes"), list)
            or not all(valid_hash(value) for value in document["hashes"])
            or not isinstance(document.get("mirrors"), list)
            or not all(isinstance(name, str) for name in document["mirrors"])
        ):
            raise ValueError("The queue has an unsupported or incomplete format.")
        document["hashes"] = list(dict.fromkeys(value.lower() for value in document["hashes"]))
        return document
    except (OSError, ValueError) as error:
        raise DownloadError(f"Cannot read the saved download queue: {error}") from error


def _download_index(directory):
    path = Path(directory) / INDEX_FILE
    empty = {"version": 2, "hashes": {}, "archives": {}, "installed": {}, "outcomes": {}}
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_QUEUE:
            return empty
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or not isinstance(saved.get("hashes"), dict):
            return empty
        return {
            "version": saved.get("version", 1),
            "hashes": saved["hashes"],
            "archives": saved.get("archives", {})
            if saved.get("version") == 2 and isinstance(saved.get("archives"), dict)
            else {},
            "installed": saved.get("installed", {})
            if isinstance(saved.get("installed"), dict)
            else {},
            "outcomes": saved.get("outcomes", {})
            if isinstance(saved.get("outcomes"), dict)
            else {},
            "history_imported": saved.get("history_imported") is True,
        }
    except (ValueError, OSError):
        return empty


def _archive_path(directory, filename):
    if (
        not isinstance(filename, str)
        or not filename.endswith(".osz")
        or any(character in filename for character in ("/", "\\", ":", "\x00"))
        or Path(filename).name != filename
    ):
        return None
    return Path(directory) / filename


def _archive_signature(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise DownloadError("A saved archive is no longer an ordinary file.")
    signature = {
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "device": info.st_dev,
        "inode": info.st_ino,
    }
    if os.name == "nt":
        # Python 3.12 st_ctime on Windows is creation time. Read the native
        # change timestamp too, so restoring mtime cannot hide a changed file.
        signature["change_time"] = _windows_change_time(path)
    return signature


def _windows_change_time(path):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class BasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation", ctypes.c_longlong),
            ("access", ctypes.c_longlong),
            ("write", ctypes.c_longlong),
            ("change", ctypes.c_longlong),
            ("attributes", wintypes.DWORD),
        ]

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    library.GetFileInformationByHandleEx.restype = wintypes.BOOL
    with path.open("rb") as stream:
        info = BasicInfo()
        if not library.GetFileInformationByHandleEx(
            msvcrt.get_osfhandle(stream.fileno()),
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.change


def _completed_archive(path, record):
    """Cheap identity check of a previously verified file; never open ZIP contents."""
    try:
        if not isinstance(record, dict) or record.get("signature") != _archive_signature(path):
            return None
        maps = record.get("maps")
        if not isinstance(maps, dict) or not 1 <= len(maps) <= 20_000:
            return None
        for checksum, details in maps.items():
            if (
                not valid_hash(checksum)
                or checksum != checksum.lower()
                or not _valid_map_details(details)
            ):
                return None
        return maps
    except (OSError, DownloadError):
        return None


def _valid_map_details(details):
    return (
        isinstance(details, dict)
        and all(
            isinstance(details.get(k, ""), str) and len(details.get(k, "")) <= 2048
            for k in ("Title", "Artist", "Difficulty", "Mode")
        )
        and all(
            v is None or (type(v) is int and v > 0)
            for v in (details.get("BeatmapId"), details.get("SetId"))
        )
    )


def _saved_outcomes(directory, index, stop):
    outcomes = dict(index["outcomes"])
    if index.get("history_imported"):
        return outcomes
    # Older clients kept failed states only in per-run reports. Read all runs in
    # order, preserving hashes that a later, smaller run never reached.
    reports = sorted(
        (p for p in Path(directory).glob("download-report-*.json") if not p.is_symlink()),
        key=lambda p: p.stat().st_mtime_ns,
    )
    for path in reports:
        _check_cancel(stop)
        try:
            if not path.is_file() or path.stat().st_size > MAX_QUEUE:
                continue
            report = json.loads(path.read_bytes())
            for result in report.get("results", []):
                if not isinstance(result, dict) or not valid_hash(result.get("hash")):
                    continue
                state = result.get("state")
                if state in ("Ready", "Failed", "Cancelled"):
                    outcomes[result["hash"].lower()] = {
                        "state": state,
                        "message": str(result.get("message", ""))[:2048],
                    }
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return outcomes


def _installed_completions(directory, hashes, index, completed, stop):
    root = Path(directory).resolve()
    records = dict(index["installed"])
    wanted = set(hashes) - completed.keys()
    for checksum in list(wanted):
        record = records.get(checksum)
        try:
            path = root / record["file"]
            if (
                path.suffix.lower() != ".osu"
                or not _valid_map_details(record.get("details"))
                or path.is_symlink()
                or not path.resolve().is_relative_to(root)
                or _archive_signature(path) != record["signature"]
            ):
                continue
            completed[checksum] = {
                "hash": checksum,
                "state": "Ready",
                "file": str(path.resolve()),
                "details": record["details"],
                "mirror": "Installed",
                "reused": True,
                "installed": True,
                "verification": "unchanged",
            }
            wanted.remove(checksum)
        except (TypeError, KeyError, OSError, DownloadError):
            continue
    candidates, metadata = set(), {}
    for filename, record in index["archives"].items():
        maps = record.get("maps", {}) if isinstance(record, dict) else {}
        if not isinstance(maps, dict):
            continue
        relevant = wanted.intersection(maps)
        match = re.fullmatch(r"(\d+)(?:-[0-9a-f]+)?\.osz", filename)
        if relevant and match:
            candidates.add(int(match[1]))
            metadata.update({h: maps[h] for h in relevant if _valid_map_details(maps[h])})
    if not candidates:
        return records
    # osu! stable consumes .osz files placed in Songs. Recognise the resulting
    # folders only after checking exact .osu bytes, never just a set ID/name.
    for folder in root.iterdir():
        _check_cancel(stop)
        match = re.match(r"(\d+)(?:\s|$)", folder.name)
        if (
            not match
            or int(match[1]) not in candidates
            or folder.is_symlink()
            or not folder.is_dir()
        ):
            continue
        for path in folder.iterdir():
            _check_cancel(stop)
            if path.suffix.lower() != ".osu" or path.is_symlink():
                continue
            try:
                before = _archive_signature(path)
                if before["size"] > MAX_OSU:
                    continue
                checksum = hashlib.md5(usedforsecurity=False)
                size = 0
                with path.open("rb") as stream:
                    while block := stream.read(CHUNK):
                        _check_cancel(stop)
                        size += len(block)
                        if size > MAX_OSU:
                            raise DownloadError("An installed .osu file exceeds 32 MiB.")
                        checksum.update(block)
                checksum = checksum.hexdigest()
                if checksum not in wanted or _archive_signature(path) != before:
                    continue
                details = metadata.get(checksum, {})
                records[checksum] = {
                    "file": path.relative_to(root).as_posix(),
                    "signature": before,
                    "details": details,
                }
                completed[checksum] = {
                    "hash": checksum,
                    "state": "Ready",
                    "file": str(path.resolve()),
                    "details": details,
                    "mirror": "Installed",
                    "reused": True,
                    "installed": True,
                    "verification": "exact MD5",
                }
                wanted.remove(checksum)
            except (OSError, DownloadError):
                continue
    return records


def load_download_progress(directory, stop=None, *, hashes=None):
    """Restore archives, failure history and exact installed files without network or writes."""
    queue = read_download_queue(directory)
    if queue is None:
        return None
    stop = stop or threading.Event()
    hashes = queue["hashes"] if hashes is None else hashes
    index, completed, checked = _download_index(directory), {}, {}
    outcomes = _saved_outcomes(directory, index, stop)
    for checksum in hashes:
        if stop:
            _check_cancel(stop)
        old = index["hashes"].get(checksum)
        path = _archive_path(directory, old.get("file")) if isinstance(old, dict) else None
        if path is None:
            continue
        if path not in checked:
            checked[path] = _completed_archive(path, index["archives"].get(path.name))
        maps = checked[path]
        if maps and checksum in maps:
            completed[checksum] = {
                "hash": checksum,
                "state": "Ready",
                "file": str(path.resolve()),
                "details": maps[checksum],
                "set_id": maps[checksum].get("SetId"),
                "mirror": "Saved",
                "reused": True,
                "verification": "unchanged",
            }
    installed = _installed_completions(directory, hashes, index, completed, stop)
    failed = {
        h: {"hash": h, **outcomes[h]}
        for h in hashes
        if h not in completed
        and isinstance(outcomes.get(h), dict)
        and outcomes[h].get("state") == "Failed"
    }
    return {
        **queue,
        "completed": completed,
        "failed": failed,
        "installed": installed,
        "outcomes": outcomes,
        "legacy_index": index["version"] != 2,
    }


class Downloader:
    def __init__(
        self, mirrors=MIRRORS, client=None, interval=1.0, now=time.monotonic, *, report_dir=None
    ):
        self.mirrors = tuple(mirrors)
        self.client = client or HttpClient()
        self.interval = interval
        self.now = now
        self.last_request = {}
        self.cooldowns = {}
        self.failures = {}
        self.report_dir = report_dir
        self.official_lookup = None

    def _open(self, mirror, url, stop):
        _check_cancel(stop)
        now = self.now()
        if self.cooldowns.get(mirror.name, 0) > now:
            raise DownloadError(f"Cooling down for {self.cooldowns[mirror.name] - now:.0f}s")
        delay = self.interval - (now - self.last_request.get(mirror.name, -1e9))
        if delay > 0 and stop.wait(delay):
            raise Cancelled()
        self.last_request[mirror.name] = self.now()
        try:
            return self.client.open(url)
        except urllib.error.HTTPError as error:
            if error.code in (429, 503):
                seconds = 60
                header = error.headers.get("Retry-After", "") if error.headers else ""
                try:
                    seconds = max(1, int(header))
                except ValueError:
                    try:
                        seconds = max(
                            1, int(parsedate_to_datetime(header).timestamp() - time.time())
                        )
                    except (ValueError, TypeError, OverflowError):
                        pass
                self.cooldowns[mirror.name] = self.now() + seconds
            elif error.code >= 500 or error.code == 403:
                self._network_failure(mirror)
            code = error.code
            error.close()
            raise DownloadError(f"HTTP {code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            self._network_failure(mirror)
            raise DownloadError("Connection failed: " + str(error)) from error

    def _network_failure(self, mirror):
        self.failures[mirror.name] = self.failures.get(mirror.name, 0) + 1
        if self.failures[mirror.name] >= 2:
            self.cooldowns[mirror.name] = self.now() + 60

    def _resolve(self, checksum, stop, emit, attempts):
        for mirror in self.mirrors:
            if not mirror.lookup:
                continue
            emit({"kind": "item", "hash": checksum, "state": "Resolving", "mirror": mirror.name})
            try:
                with self._open(mirror, mirror.lookup.format(md5=checksum), stop) as response:
                    data = bytearray()
                    for block in self._blocks(response, stop):
                        data.extend(block)
                        if len(data) > MAX_JSON:
                            raise DownloadError("The lookup response exceeds 8 MiB.")
                _check_cancel(stop)
                if len(data) > MAX_JSON:
                    raise DownloadError("The lookup response exceeds 8 MiB.")
                set_id, details = resolve_response(mirror, json.loads(data), checksum)
                details = {
                    key: value[:2048]
                    if isinstance(value, str)
                    else value
                    if key == "BeatmapId"
                    else ""
                    for key, value in details.items()
                }
                emit({"kind": "metadata", "hash": checksum, "details": details, "set_id": set_id})
                return set_id, details
            except (DownloadError, ValueError, OSError, TimeoutError) as error:
                attempts.append({"stage": "lookup", "mirror": mirror.name, "error": str(error)})
                emit(
                    {
                        "kind": "log",
                        "message": f"{mirror.name} lookup: {error}. Trying next mirror.",
                    }
                )
        if self.official_lookup is not None:
            emit({"kind": "item", "hash": checksum, "state": "Resolving", "mirror": "osu! API"})
            try:
                set_id, details = self.official_lookup.resolve(checksum, stop)
                emit({"kind": "metadata", "hash": checksum, "details": details, "set_id": set_id})
                return set_id, details
            except DownloadError as error:
                attempts.append({"stage": "lookup", "mirror": "osu! API", "error": str(error)})
        raise DownloadError("No enabled lookup provider could resolve this exact MD5.")

    def _blocks(self, response, stop):
        started = self.now()
        read = getattr(response, "read1", response.read)
        while data := read(CHUNK):
            _check_cancel(stop)
            if self.now() - started > 180:
                raise DownloadError("The response exceeded its three-minute limit.")
            yield data

    def _download(self, mirror, set_id, path, checksum, stop, emit):
        started = self.now()
        with self._open(mirror, mirror.download.format(id=set_id), stop) as response:
            kind = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if kind in ("text/html", "application/json", "application/problem+json"):
                raise DownloadError(
                    "Mirror returned a page or JSON instead of an archive "
                    "(possibly a login, CAPTCHA, or upstream error)."
                )
            try:
                length = int(response.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                length = 0
            if length > MAX_ARCHIVE:
                raise DownloadError("The download exceeds 512 MiB.")
            size, last_update = 0, -1e9
            with path.open("wb") as output:
                for data in self._blocks(response, stop):
                    _check_cancel(stop)
                    size += len(data)
                    if size > MAX_ARCHIVE or self.now() - started > 180:
                        raise DownloadError("The download exceeds its size or three-minute limit.")
                    output.write(data)
                    if self.now() - last_update >= 0.2:
                        emit(
                            {
                                "kind": "bytes",
                                "hash": checksum,
                                "received": size,
                                "total": length,
                                "mirror": mirror.name,
                            }
                        )
                        last_update = self.now()
                if not size or (length and size != length):
                    raise DownloadError("The download is empty or incomplete.")
        _check_cancel(stop)

    def run(self, hashes, directory, emit=lambda _event: None, stop=None, *, retry_failed=False):
        stop = stop or threading.Event()
        hashes = list(dict.fromkeys(value.lower() for value in hashes if valid_hash(value)))
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise DownloadError("Choose an existing download folder.")
        if not self.mirrors:
            raise DownloadError("Enable at least one mirror.")
        saved_queue = read_download_queue(directory)
        queue_path = directory / QUEUE_FILE
        _private_json(
            queue_path,
            {
                "version": 1,
                "updated_at": datetime.now(UTC).isoformat(),
                "hashes": list(dict.fromkeys((saved_queue or {}).get("hashes", []) + hashes)),
                "mirrors": [mirror.name for mirror in self.mirrors],
            },
        )
        index_path = directory / INDEX_FILE
        saved_index = _download_index(directory)
        preparation_cancelled = False
        try:
            progress = load_download_progress(directory, stop, hashes=hashes)
        except Cancelled:
            preparation_cancelled = True
            progress = {
                "completed": {},
                "failed": {},
                "installed": saved_index["installed"],
                "outcomes": saved_index["outcomes"],
            }
        outcomes = progress["outcomes"]
        saved_index.update(
            installed=progress["installed"],
            outcomes=outcomes,
            history_imported=saved_index.get("history_imported", False)
            if preparation_cancelled
            else True,
        )
        restored = {**progress["failed"], **progress["completed"]}
        work = [
            h
            for h in hashes
            if h not in progress["completed"] and (retry_failed or h not in progress["failed"])
        ]
        if preparation_cancelled:
            work = []
        if retry_failed:
            for h in work:
                if h in progress["failed"]:
                    restored[h] = {
                        "hash": h,
                        "state": "Queued",
                        "message": "Explicit retry requested.",
                    }
        if not preparation_cancelled:
            emit({"kind": "snapshot", "states": restored, "hashes": hashes, "remaining": len(work)})
        index, archives = saved_index["hashes"], saved_index["archives"]
        available, checked = {}, {}
        results = {h: {**r, "skipped": True} for h, r in restored.items() if h not in work}
        unchanged, newly_verified = set(), set()
        index_dirty = False

        def read_existing(path, maps=None):
            nonlocal index_dirty
            if path not in checked:
                cached = _completed_archive(path, archives.get(path.name)) if maps is None else None
                if cached is not None:
                    checked[path] = cached
                    unchanged.add(path)
                else:
                    before = _archive_signature(path)
                    checked[path] = maps if maps is not None else inspect_archive(path, stop)
                    if _archive_signature(path) != before:
                        raise DownloadError("The saved archive changed during verification.")
                    archives[path.name] = {"signature": before, "maps": checked[path]}
                    if maps is not None:
                        newly_verified.add(path)
                    index_dirty = True
                for value, details in checked[path].items():
                    available[value] = (path, details)
                    index[value] = {"file": path.name, "set_id": details.get("SetId")}

        def save_index():
            _private_json(
                index_path,
                {
                    **saved_index,
                    "version": 2,
                    "hashes": index,
                    "archives": archives,
                    "outcomes": outcomes,
                },
            )

        for checksum in work:
            attempts = []
            set_id, details = None, {}
            result = {"hash": checksum, "state": "Failed", "attempts": attempts}
            try:
                _check_cancel(stop)
                old = index.get(checksum)
                if checksum not in available and isinstance(old, dict):
                    path = _archive_path(directory, old.get("file"))
                    if path is not None:
                        if path.is_file() and not path.is_symlink():
                            try:
                                read_existing(path)
                            except (DownloadError, OSError) as error:
                                emit(
                                    {
                                        "kind": "log",
                                        "message": f"Cached archive needs replacement: {error}",
                                    }
                                )
                if checksum not in available:
                    set_id, details = self._resolve(checksum, stop, emit, attempts)
                    path = directory / f"{set_id}.osz"
                    if path.is_file() and not path.is_symlink():
                        try:
                            read_existing(path)
                        except (DownloadError, OSError):
                            pass
                    if checksum not in available:
                        self._fetch_set(
                            set_id, checksum, directory, stop, emit, attempts, read_existing
                        )
                path, details = available[checksum]
                result.update(
                    state="Ready",
                    file=str(path),
                    details=details,
                    set_id=details.get("SetId") or set_id,
                    reused=path in unchanged,
                    verification="unchanged" if path in unchanged else "verified",
                )
                if path in unchanged:
                    result["mirror"] = "Saved"
                if index_dirty:
                    # Publishing a new file links then removes its .part name. Capture
                    # ctime after that unlink, so the first resume can use this record.
                    for fresh_path in newly_verified:
                        archives[fresh_path.name]["signature"] = _archive_signature(fresh_path)
                    newly_verified.clear()
                    save_index()
                    index_dirty = False
            except Cancelled:
                result.update(state="Cancelled", message="Cancelled; partial download removed.")
            except (DownloadError, OSError, ValueError) as error:
                result.update(message=str(error), set_id=set_id, details=details)
            results[checksum] = result
            outcomes[checksum] = {
                "state": result["state"],
                "message": result.get("message", "")[:2048],
            }
            emit({"kind": "result", **result})
            if stop.is_set():
                break
        save_index()
        results = [results[h] for h in hashes if h in results]
        ready, remaining, failed, installed = download_counts(
            hashes, {r["hash"]: r for r in results}
        )
        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "mirrors": [asdict(m) for m in self.mirrors],
            "requested": len(hashes),
            "cancelled": stop.is_set(),
            "preparation_cancelled": preparation_cancelled,
            "results": results,
            "ready": ready,
            "remaining": remaining,
            "failed": failed,
            "installed": installed,
        }
        report_path = _write_report(report, self.report_dir)
        return {**report, "report_path": str(report_path), "queue_path": str(queue_path)}

    def _fetch_set(self, set_id, checksum, directory, stop, emit, attempts, remember):
        for mirror in self.mirrors:
            handle, name = tempfile.mkstemp(prefix=f".{set_id}-", suffix=".part", dir=directory)
            os.close(handle)
            temporary = Path(name)
            try:
                emit(
                    {
                        "kind": "item",
                        "hash": checksum,
                        "state": "Downloading",
                        "mirror": mirror.name,
                        "set_id": set_id,
                    }
                )
                self._download(mirror, set_id, temporary, checksum, stop, emit)
                emit(
                    {"kind": "item", "hash": checksum, "state": "Verifying", "mirror": mirror.name}
                )
                maps = inspect_archive(temporary, stop)
                if checksum not in maps:
                    raise DownloadError(
                        "Archive lacks the required MD5; a different revision was returned."
                    )
                if maps[checksum].get("SetId") not in (None, set_id):
                    raise DownloadError("The archive contains a different beatmapset ID.")
                destination = directory / f"{set_id}.osz"
                while True:
                    try:
                        os.link(temporary, destination)
                        break
                    except FileExistsError:
                        destination = directory / f"{set_id}-{uuid.uuid4().hex[:8]}.osz"
                remember(destination, maps)
                emit({"kind": "log", "message": f"Verified {destination.name} from {mirror.name}."})
                return
            except (DownloadError, OSError, ValueError) as error:
                attempts.append({"stage": "download", "mirror": mirror.name, "error": str(error)})
                emit(
                    {
                        "kind": "log",
                        "message": f"{mirror.name} download: {error}. Trying next mirror.",
                    }
                )
            finally:
                temporary.unlink(missing_ok=True)
        raise DownloadError(
            "All enabled mirrors failed or lack the exact .osu MD5. See attempts in the report."
        )
