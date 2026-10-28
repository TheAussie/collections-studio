"""Offline update download/replacement checks using disposable fake executables."""

import hashlib
import io
import json
import sys
from types import SimpleNamespace

from tools.app_updates import API, REPOSITORY, check_for_update, download_update
from tools.beatmap_downloads import _private_json
from tools.update_install import apply_update, cleanup_update, confirm_startup, create_stage, digest


def run_update_smoke(folder):
    target = (folder / "synthetic portable app").resolve()
    target.write_bytes(b"previous synthetic executable")
    target.chmod(0o700)
    stage = create_stage(target)
    name = (
        "CollectionsStudio-windows-x64.exe"
        if sys.platform == "win32"
        else "CollectionsStudio-linux-x64"
    )
    data = (b"MZ00" if sys.platform == "win32" else b"\x7fELF") + b"synthetic update fixture"
    checksum = hashlib.sha256(data).hexdigest()
    base = f"https://github.com/{REPOSITORY}/releases/download/v9.9.9/"
    release = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": asset,
                "size": len(data),
                "state": "uploaded",
                "browser_download_url": base + asset,
            }
            for asset in (name, "SHA256SUMS")
        ],
    }

    class OfflineClient:
        def open(self, url):
            if url == API:
                return io.BytesIO(json.dumps(release).encode())
            if url == base + "SHA256SUMS":
                return io.BytesIO(f"{checksum}  {name}\n".encode())
            if url == base + name:
                return io.BytesIO(data)
            raise AssertionError("Live update HTTP is forbidden in the packaged self-test")

    info = check_for_update("0.0.0", client=OfflineClient())
    assert download_update(info, stage, client=OfflineClient()) == checksum
    plan = stage / "plan.json"
    _private_json(
        plan,
        {
            "format": 1,
            "pid": 123456,
            "target": str(target),
            "old_sha256": digest(target),
            "new_sha256": checksum,
            "version": "9.9.9",
            "open_file": "",
        },
    )

    def launch(_arguments):
        confirm_startup(plan, target, "9.9.9")
        return SimpleNamespace(poll=lambda: None)

    apply_update(plan, wait_parent=lambda _pid: None, launch=launch)
    assert target.read_bytes() == data
    assert cleanup_update(plan) and not stage.exists()
