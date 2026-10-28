"""One-shot portable replacement helper; never a service or database migration."""

import ctypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.app_updates import UpdateError
from tools.beatmap_downloads import _check_cancel, _private_json

PREFIX = ".collections-studio-update-"
FILES = {
    "plan.json",
    "result.json",
    "ready",
    "ack",
    "complete",
    "abort",
    "download",
    "download.part",
    "helper",
    "helper.exe",
    "previous",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def portable_target():
    if not getattr(sys, "frozen", False):
        raise UpdateError(
            "Automatic replacement is available in the portable executable. "
            "Source checkouts update through Git."
        )
    details = json.loads((Path(sys._MEIPASS) / "app-version.json").read_text(encoding="utf-8"))
    if details.get("format") != "onefile":
        raise UpdateError("Automatic replacement requires the single-file portable release.")
    return Path(sys.executable).resolve(strict=True)


def create_stage(target):
    target = Path(target).resolve(strict=True)
    if not target.is_file():
        raise UpdateError("The running executable is unavailable.")
    try:
        return Path(tempfile.mkdtemp(prefix=PREFIX, dir=target.parent))
    except OSError as error:
        raise UpdateError(
            "The application folder is not writable. "
            "Move the portable app to a folder you own before updating."
        ) from error


def _plan(path):
    path = Path(path).resolve(strict=True)
    if path.name != "plan.json" or not path.parent.name.startswith(PREFIX):
        raise UpdateError("Invalid private update plan location.")
    with path.open("rb") as stream:
        raw = stream.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise UpdateError("Update plan is too large.")
    data = json.loads(raw)
    target = Path(data["target"])
    if (
        data.get("format") != 1
        or not target.is_absolute()
        or target.parent != path.parent.parent
        or target.resolve() != target
    ):
        raise UpdateError("The update plan does not match its application folder.")
    if type(data.get("pid")) is not int or data["pid"] <= 0:
        raise UpdateError("Invalid update parent process.")
    for key in ("old_sha256", "new_sha256"):
        value = data.get(key)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise UpdateError("Invalid update checksum.")
    if not isinstance(data.get("version"), str) or not isinstance(data.get("open_file", ""), str):
        raise UpdateError("Invalid update restart details.")
    return path, data, target


def child_environment():
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    # A new one-file process must not inherit the old extracted runtime's search path.
    original = environment.get("LD_LIBRARY_PATH_ORIG")
    if original is None:
        environment.pop("LD_LIBRARY_PATH", None)
    else:
        environment["LD_LIBRARY_PATH"] = original
    for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment.pop(key, None)
    return environment


def _launch(arguments):
    options = {"env": child_environment(), "close_fds": True}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(list(map(str, arguments)), **options)


def start_helper(stage, target, checksum, version, open_file="", *, stop=None):
    stage, target = Path(stage), Path(target).resolve(strict=True)
    helper = stage / ("helper.exe" if sys.platform == "win32" else "helper")
    if digest(stage / "download") != checksum:
        raise UpdateError("The verified update changed before installation.")
    shutil.copy2(target, helper)
    helper.chmod(stat.S_IMODE(target.stat().st_mode) & 0o777)
    path = stage / "plan.json"
    _private_json(
        path,
        {
            "format": 1,
            "pid": os.getpid(),
            "target": str(target),
            "old_sha256": digest(target),
            "new_sha256": checksum,
            "version": version,
            "open_file": open_file,
        },
    )
    if stop is not None:
        _check_cancel(stop)
    process = _launch([helper, "--apply-update", path])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if (stage / "ready").is_file():
            return path
        if process.poll() is not None:
            (stage / "abort").touch()
            raise UpdateError(
                "The temporary update helper could not start. The current app is unchanged."
            )
        if stop is not None:
            _check_cancel(stop)
        time.sleep(0.05)
    (stage / "abort").touch()
    raise UpdateError("The update helper did not become ready. The current app is unchanged.")


def wait_for_exit(pid, timeout=120):
    if pid == os.getpid():
        raise UpdateError("The updater cannot wait for itself.")
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # Already exited.
                return
            raise UpdateError("Could not wait for the old client to close.")
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise UpdateError("The old client did not close in time. No files were replaced.")
        finally:
            kernel.CloseHandle(handle)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise UpdateError("The old client did not close in time. No files were replaced.")


def _replace_wait(source, target):
    deadline = time.monotonic() + 30
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)  # Windows one-file bootloader may still hold the old EXE.


def apply_update(path, *, wait_parent=wait_for_exit, launch=_launch, confirmation_timeout=60):
    # Reuse Studio's OS-backed, crash-released file lease. Two client instances
    # must not race to replace the same executable after both have checked it.
    from tools.collection_save import database_save_lock

    path, _data, target = _plan(path)
    with database_save_lock(target, realm=False):
        return _apply_update(
            path, wait_parent=wait_parent, launch=launch, confirmation_timeout=confirmation_timeout
        )


def _apply_update(path, *, wait_parent, launch, confirmation_timeout):
    path, data, target = _plan(path)
    stage, backup = path.parent, path.parent / "previous"
    candidate = stage / "download"
    if (stage / "abort").is_file():
        return
    if candidate.is_symlink() or backup.is_symlink():
        raise UpdateError("Update files must be ordinary private files.")
    if digest(candidate) != data["new_sha256"] or digest(target) != data["old_sha256"]:
        raise UpdateError("Application or update changed. No files were replaced.")
    if backup.exists():
        raise UpdateError("This update plan has already been used.")
    (stage / "ready").write_text("ready", encoding="utf-8")
    wait_parent(data["pid"])
    if (stage / "abort").exists():
        return
    if digest(candidate) != data["new_sha256"] or digest(target) != data["old_sha256"]:
        raise UpdateError("Application or update changed while closing. No files were replaced.")
    mode = stat.S_IMODE(target.stat().st_mode) & 0o777
    arguments = [str(target), "--finish-update", str(path)]
    if data["open_file"]:
        arguments += ["--file", data["open_file"]]
    moved, process = False, None
    try:
        candidate.chmod(mode)
        _replace_wait(target, backup)
        moved = True
        _replace_wait(candidate, target)
        _private_json(stage / "result.json", {"status": "installed", "version": data["version"]})
        process = launch(arguments)
        deadline = time.monotonic() + confirmation_timeout
        while time.monotonic() < deadline:
            if (stage / "ack").is_file():
                (stage / "complete").touch()
                return
            if process.poll() is not None:
                raise UpdateError("The new client exited before confirming startup.")
            time.sleep(0.1)
        # A still-running new client may just be slow. Keep its backup, without killing it.
        _private_json(
            stage / "result.json",
            {
                "status": "unconfirmed",
                "version": data["version"],
                "message": "Startup was not confirmed; "
                "the previous executable remains in this update folder.",
            },
        )
        (stage / "complete").touch()
    except Exception:
        if process is not None and process.poll() is None:
            raise
        if moved and backup.is_file():
            _replace_wait(backup, target)
        _private_json(
            stage / "result.json",
            {
                "status": "failed",
                "message": "The update could not start. The previous executable was restored.",
            },
        )
        (stage / "complete").touch()
        launch(arguments)


def confirm_startup(path, target, version):
    path, data, expected_target = _plan(path)
    if expected_target != Path(target).resolve():
        raise UpdateError("Update confirmation belongs to a different executable.")
    result = json.loads((path.parent / "result.json").read_text(encoding="utf-8"))
    expected_hash = data["old_sha256"] if result["status"] == "failed" else data["new_sha256"]
    if digest(target) != expected_hash or (
        result["status"] != "failed" and version != data["version"]
    ):
        raise UpdateError("The restarted executable does not match the verified release.")
    (path.parent / "ack").write_text(str(os.getpid()), encoding="utf-8")
    return result


def cleanup_update(path):
    path, _data, _target = _plan(path)
    if not (path.parent / "ack").is_file() or not (path.parent / "complete").is_file():
        return False
    for name in FILES - {"plan.json", "ack"}:
        try:
            (path.parent / name).unlink(missing_ok=True)
        except OSError:
            return False
    try:
        (path.parent / "ack").unlink(missing_ok=True)
        path.unlink()
        path.parent.rmdir()
        return True
    except OSError:
        return False
