"""Rehearse a native one-file handoff on private copies, with no live HTTP or databases."""

import argparse
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.beatmap_downloads import _private_json  # noqa: E402
from tools.update_install import child_environment, create_stage, digest  # noqa: E402


def image_path(pid):
    if sys.platform != "win32":
        return Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise RuntimeError("Cannot verify the private test process image")
    try:
        buffer, size = ctypes.create_unicode_buffer(32768), ctypes.c_uint32(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise RuntimeError("Cannot identify the private test process image")
        return Path(buffer.value).resolve()
    finally:
        kernel.CloseHandle(handle)


def rehearse(binary, output, version):
    if output.exists():
        raise ValueError("Choose an unused rehearsal output directory")
    output.mkdir(parents=True)
    profile = output / "profile"
    fixture = output / "fixture"
    fixture.mkdir()
    target = fixture / ("CollectionsStudio.exe" if sys.platform == "win32" else "CollectionsStudio")
    shutil.copy2(binary, target)
    old_inode = target.stat().st_ino
    environment = child_environment()
    environment.update(
        QT_QPA_PLATFORM="offscreen",
        XDG_CONFIG_HOME=str(profile / "config"),
        XDG_CACHE_HOME=str(profile / "cache"),
        XDG_DATA_HOME=str(profile / "data"),
        LOCALAPPDATA=str(profile / "local"),
        APPDATA=str(profile / "roaming"),
        PATH="",
    )
    old = subprocess.Popen(
        [str(target), "--self-test", "--report", str(output / "old-self-test.json")],
        env=environment,
    )
    stage = create_stage(target)
    shutil.copy2(binary, stage / "download")
    helper = stage / ("helper.exe" if sys.platform == "win32" else "helper")
    shutil.copy2(binary, helper)
    plan = stage / "plan.json"
    checksum = digest(binary)
    _private_json(
        plan,
        {
            "format": 1,
            "pid": old.pid,
            "target": str(target),
            "old_sha256": checksum,
            "new_sha256": checksum,
            "version": version,
            "open_file": "",
        },
    )
    updater = subprocess.Popen([str(helper), "--apply-update", str(plan)], env=environment)
    new_pid, installed = None, False
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            old.poll()  # Reap the old fixture, so a POSIX zombie cannot look alive to the helper.
            result_file = stage / "result.json"
            if result_file.is_file():
                try:
                    result = json.loads(result_file.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    result = {}
                if result.get("status") == "failed":
                    raise RuntimeError("Native replacement rolled back instead of installing")
                installed = installed or result.get("status") == "installed"
            if (stage / "ack").is_file():
                new_pid = int((stage / "ack").read_text(encoding="utf-8"))
            if new_pid and updater.poll() is not None and not stage.exists():
                break
            if updater.poll() not in (None, 0):
                raise RuntimeError("Private native update helper failed")
            time.sleep(0.05)
        else:
            raise RuntimeError("Private native update did not confirm and clean up in time")
        if (
            not installed
            or old.wait(timeout=10) != 0
            or updater.wait(timeout=10) != 0
            or digest(target) != checksum
        ):
            raise RuntimeError("Private native update did not preserve the expected executable")
        if old_inode and target.stat().st_ino == old_inode:
            raise RuntimeError("The private executable was not physically replaced")
        if image_path(new_pid) != target.resolve():
            raise RuntimeError("Refusing to stop a process outside this private rehearsal")
        os.kill(new_pid, signal.SIGTERM)  # Only the acknowledged GUI in this fixture directory.
        new_pid = None
        deadline = time.monotonic() + 30
        while True:
            try:
                target.unlink()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        (output / "native-update-rehearsal.json").write_text(
            json.dumps(
                {
                    "Passed": True,
                    "Platform": sys.platform,
                    "Version": version,
                    "BinarySha256": checksum,
                    "PrivateCopiesOnly": True,
                    "ParentExitAndReplacement": True,
                    "NewGuiStartupConfirmed": True,
                    "TemporaryHelperCleaned": True,
                    "LiveHttp": False,
                    "GameDatabases": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        if new_pid is not None:
            try:
                if image_path(new_pid) == target.resolve():
                    os.kill(new_pid, signal.SIGTERM)
            except (OSError, RuntimeError):
                pass
        if old.poll() is None:
            old.terminate()
            old.wait(timeout=10)
        if updater.poll() is None:
            updater.terminate()
            updater.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    rehearse(args.binary.resolve(strict=True), args.output.resolve(), args.version)
    print("Native private-copy update rehearsal passed.")


if __name__ == "__main__":
    main()
