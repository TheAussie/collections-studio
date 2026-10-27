"""Back up an opened database, then publish an already verified replacement."""

import os
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tools.beatmap_downloads import _private_json
from tools.collection_application import save_workspace
from tools.stable_collections import digest


def _windows_lock(fd):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(Overlapped),
    ]
    library.LockFileEx.restype = wintypes.BOOL
    library.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(Overlapped),
    ]
    library.UnlockFileEx.restype = wintypes.BOOL
    handle, position = msvcrt.get_osfhandle(fd), Overlapped()
    if not library.LockFileEx(handle, 3, 0, 1, 0, ctypes.byref(position)):
        raise ctypes.WinError(ctypes.get_last_error())
    return lambda: library.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(position))


@contextmanager
def database_save_lock(path, *, realm):
    # Realm Core holds a shared lock here for the lifetime of an open database:
    # flock on Linux, LockFileEx on byte zero on Windows. Never delete this file.
    # Stable's lock coordinates Studio instances; osu!stable must be closed.
    suffix = ".lock" if realm else ".collections-studio.lock"
    lock_path = Path(str(path) + suffix)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    unlock = None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("The database lock path is not a regular file.")
        try:
            if sys.platform == "win32":
                unlock = _windows_lock(fd)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                def unlock():
                    fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as error:
            raise PermissionError(
                "This database is in use. Close osu! and any other Studio save, then try again."
            ) from error
        yield
    finally:
        try:
            if unlock:
                unlock()
        finally:
            os.close(fd)


def _identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Save requires a regular database file, not a symbolic link.")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _check_source(path, expected, identity):
    if _identity(path) != identity or digest(path) != expected:
        raise ValueError(
            "The source changed since opening or during save. Reopen it before saving."
        )


def _sync_file(path):
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _sync_directory(path):
    if sys.platform != "win32":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _backup(source, backup, expected):
    # Exclusive creation and a full, synced copy: an older backup is never replaced.
    created = False
    try:
        with backup.open("xb") as output:
            created = True
            if sys.platform != "win32":
                backup.chmod(0o600)
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if digest(backup) != expected:
            raise ValueError("The backup did not match the opened database. Nothing was replaced.")
        _sync_directory(backup.parent)
    except BaseException:
        if created:
            backup.unlink(missing_ok=True)
        raise


def save_open_workspace(workspace, backend, *, new_path=None):
    """Save to the opened path; new stable files require an unused chosen filename.

    A failure before atomic publication leaves the source intact. Once published,
    report/directory-sync failures are returned as warnings, so successful saves do
    not incorrectly remain dirty. The byte-verified backup is retained on failures.
    """
    existing = bool(workspace.source_path)
    if not existing and (workspace.format != "stable" or not new_path):
        raise ValueError("Choose a filename for the new collection.db first.")
    if existing and new_path:
        raise ValueError("Use Save a copy to save an opened database somewhere else.")
    path = Path(workspace.source_path if existing else new_path).absolute()
    if not path.parent.is_dir():
        raise ValueError("The database parent folder no longer exists.")
    if path.is_symlink() or (not existing and path.exists()):
        raise ValueError(
            "The destination already exists or is a link. Open it before saving changes."
        )
    tag = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:8]
    backup = path.with_name(f"{path.stem}.backup-{tag}{path.suffix}") if existing else None
    report_path = path.with_name(f"{path.stem}.save-report-{tag}.json")
    with database_save_lock(path, realm=workspace.format == "realm"):
        identity = _identity(path) if existing else None
        if existing:
            _check_source(path, workspace.source_hash, identity)
        elif path.exists() or path.is_symlink():
            raise FileExistsError("The destination now exists. Choose a new filename.")
        with tempfile.TemporaryDirectory(
            prefix=".collections-save-",
            dir=path.parent,
            ignore_cleanup_errors=True,
        ) as folder:
            stage = Path(folder) / "verified"
            report = save_workspace(workspace, stage, backend)
            staged = stage / ("collection.db" if workspace.format == "stable" else "client.realm")
            expected = report.get("OutputSha256", report.get("OutputRealmSha256"))
            if not report.get("VerifiedAfterReopen") or digest(staged) != expected:
                raise ValueError("The new database failed verification. Nothing was replaced.")
            _sync_file(staged)
            if existing:
                _check_source(path, workspace.source_hash, identity)
                _backup(path, backup, workspace.source_hash)
                _check_source(path, workspace.source_hash, identity)
            report.update(
                OutputFile=str(path),
                OutputSha256=expected,
                BackupFile=str(backup) if backup else None,
                BackupSha256=workspace.source_hash if backup else None,
                ReportPath=str(report_path),
                SaveState="prepared",
                Warnings=[],
            )
            if workspace.format == "realm":
                report.update(OutputRealm=str(path), OutputRealmSha256=expected)
            _private_json(report_path, report)
            try:
                if existing:
                    _check_source(path, workspace.source_hash, identity)
                    os.replace(staged, path)
                else:
                    # Atomic no-overwrite publication of a brand-new stable file.
                    os.link(staged, path)
            except OSError as error:
                location = f" The original backup is at {backup}." if backup else ""
                raise OSError(
                    "Save could not replace the database. Close osu! and retry." + location
                ) from error
            report["SaveState"] = "saved"
            try:
                _sync_directory(path.parent)
                _private_json(report_path, report)
            except OSError:
                report["Warnings"].append(
                    "The database was saved, but the final report or folder sync failed. "
                    "Keep the backup and check the destination before closing."
                )
            return report
