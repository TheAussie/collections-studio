import hashlib
import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from tools.app_updates import (
    API,
    REPOSITORY,
    UpdateError,
    _Redirects,
    check_for_update,
    download_update,
)
from tools.beatmap_downloads import Cancelled

DATA = b"\x7fELF" + b"synthetic executable" * 100
HASH = hashlib.sha256(DATA).hexdigest()


class Client:
    def __init__(self, release, data=DATA, sums=None):
        self.release, self.data, self.sums = release, data, sums
        self.calls = []

    def open(self, url):
        self.calls.append(url)
        if url == API:
            return io.BytesIO(json.dumps(self.release).encode())
        if url.endswith("/SHA256SUMS"):
            value = self.sums or f"{HASH}  CollectionsStudio-linux-x64\n"
            return io.BytesIO(value.encode())
        return io.BytesIO(self.data)


def release(tag="v0.1.1", system="linux"):
    name = (
        "CollectionsStudio-windows-x64.exe" if system == "win32" else "CollectionsStudio-linux-x64"
    )
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "body": "Changes",
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": len(DATA),
                "digest": "sha256:" + HASH,
                "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}",
            },
            {
                "name": "SHA256SUMS",
                "state": "uploaded",
                "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/SHA256SUMS",
            },
        ],
    }


@pytest.mark.parametrize("system", ["linux", "win32"])
def test_platform_asset_and_numeric_version_order(system):
    client = Client(release("v0.1.10", system))
    info = check_for_update("0.1.9", client=client, system=system, machine="AMD64")
    assert info.version == "0.1.10" and info.notes == "Changes"
    assert info.asset_name.endswith(".exe") is (system == "win32")
    assert check_for_update("0.1.10", client=client, system=system, machine="x86_64") is None
    assert check_for_update("0.2.0b1", client=client, system=system, machine="x86_64") is None


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_prereleases_and_drafts_never_offer_automatic_install(flag):
    value = release()
    value[flag] = True
    assert check_for_update("0.1.0", client=Client(value), system="linux", machine="x86_64") is None


@pytest.mark.parametrize(
    "change",
    [
        "foreign_host",
        "wrong_repo",
        "wrong_tag",
        "http",
        "missing_sums",
        "duplicate_asset",
        "oversized",
        "unfinished",
    ],
)
def test_untrusted_or_incomplete_release_rejected_before_download(change):
    value = release()
    asset = value["assets"][0]
    if change == "foreign_host":
        asset["browser_download_url"] = asset["browser_download_url"].replace(
            "github.com", "github.com.evil.example"
        )
    elif change == "wrong_repo":
        asset["browser_download_url"] = asset["browser_download_url"].replace(
            REPOSITORY, "other/repo"
        )
    elif change == "wrong_tag":
        asset["browser_download_url"] = asset["browser_download_url"].replace("v0.1.1", "v0.1.2")
    elif change == "http":
        asset["browser_download_url"] = asset["browser_download_url"].replace("https:", "http:")
    elif change == "missing_sums":
        value["assets"].pop()
    elif change == "duplicate_asset":
        value["assets"].append(asset.copy())
    elif change == "oversized":
        asset["size"] = 1024**3
    else:
        asset["state"] = "new"
    client = Client(value)
    with pytest.raises(UpdateError):
        check_for_update("0.1.0", client=client, system="linux", machine="x86_64")
    assert client.calls == [API]


@pytest.mark.parametrize("data", [DATA, DATA[:-1], DATA + b"extra", b"\x7fELF" + b"changed" * 100])
def test_verified_download_never_publishes_partial_or_corrupt_bytes(tmp_path, data):
    client = Client(release(), data=data)
    info = check_for_update("0.1.0", client=client, system="linux", machine="x86_64")
    if data == DATA:
        assert download_update(info, tmp_path, client=client) == HASH
        assert (tmp_path / "download").read_bytes() == DATA
    else:
        with pytest.raises(UpdateError):
            download_update(info, tmp_path, client=client)
        assert not (tmp_path / "download").exists()
    assert not (tmp_path / "download.part").exists()


def test_inconsistent_checksums_and_cancellation_keep_existing_app(tmp_path):
    app = tmp_path / "CollectionsStudio"
    app.write_bytes(b"original")
    client = Client(release(), sums="0" * 64 + "  CollectionsStudio-linux-x64\n")
    info = check_for_update("0.1.0", client=client, system="linux", machine="x86_64")
    with pytest.raises(UpdateError, match="inconsistent"):
        download_update(info, tmp_path, client=client)
    assert info.asset_url not in client.calls
    client.sums = None
    stop = threading.Event()
    with pytest.raises(Cancelled):
        download_update(info, tmp_path, client=client, stop=stop, progress=lambda _text: stop.set())
    assert app.read_bytes() == b"original" and not (tmp_path / "download.part").exists()
    assert not (tmp_path / "download").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/file",
        "file:///tmp/app",
        "https://github.com.evil.example/file",
        "https://user:pass@github.com/file",
        "https://evil.example/file",
    ],
)
def test_redirects_do_not_leave_approved_https_asset_hosts(url):
    with pytest.raises(UpdateError):
        _Redirects().redirect_request(
            urllib.request.Request("https://github.com/a"), None, 302, "", {}, url
        )


def test_rate_limit_and_unsupported_architecture_are_actionable():
    class Limited:
        def open(self, url):
            raise urllib.error.HTTPError(url, 403, "limited", {}, None)

    with pytest.raises(UpdateError, match="limiting"):
        check_for_update("0.1.0", client=Limited(), system="linux", machine="x86_64")
    with pytest.raises(UpdateError, match="x64"):
        check_for_update("0.1.0", client=Limited(), system="linux", machine="aarch64")
