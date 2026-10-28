"""Stable GitHub release checks and verified downloads; no tokens or update service."""

import hashlib
import json
import platform
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from tools.app_version import version_key
from tools.beatmap_downloads import _check_cancel

REPOSITORY = "TheAussie/collections-studio"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_BINARY = 512 * 1024 * 1024
DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}


class UpdateError(ValueError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    notes: str
    asset_name: str
    asset_url: str
    size: int
    checksums_url: str
    digest: str = ""

    @property
    def page_url(self):
        return (
            f"https://github.com/{REPOSITORY}/releases/tag/{urllib.parse.quote(self.tag, safe='')}"
        )


def _https_host(url):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise UpdateError("The update URL is not an approved HTTPS location.")
    return parsed.hostname


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if _https_host(newurl) not in DOWNLOAD_HOSTS:
            raise UpdateError("The update download redirected outside GitHub's asset hosts.")
        return super().redirect_request(request, response, code, message, headers, newurl)


class GithubTransport:
    def open(self, url):
        if _https_host(url) not in DOWNLOAD_HOSTS | {"api.github.com"}:
            raise UpdateError("The update URL is outside GitHub.")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CollectionsStudio-Updater",
                "Accept": "application/vnd.github+json"
                if url == API
                else "application/octet-stream",
            },
        )
        return urllib.request.build_opener(_Redirects()).open(request, timeout=15)


def _read(client, url, limit, stop):
    if stop is not None:
        _check_cancel(stop)
    with client.open(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("The update metadata exceeds its size limit.")
    if stop is not None:
        _check_cancel(stop)
    return data


def _asset(assets, name, tag):
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise UpdateError(
            f"The release is missing a unique {name}; try again after publication finishes."
        )
    asset = matches[0]
    url = asset.get("browser_download_url", "")
    parsed = urllib.parse.urlsplit(url)
    expected = f"/{REPOSITORY}/releases/download/{tag}/{name}"
    if (
        _https_host(url) != "github.com"
        or urllib.parse.unquote(parsed.path) != expected
        or parsed.query
        or parsed.fragment
    ):
        raise UpdateError("A release asset does not belong to the expected repository and tag.")
    if asset.get("state") != "uploaded":
        raise UpdateError("The release is still being uploaded. Try again shortly.")
    return asset


def check_for_update(current, *, client=None, system=None, machine=None, stop=None):
    system, machine = system or sys.platform, machine or platform.machine().lower()
    if system not in ("linux", "win32") or machine.lower() not in ("amd64", "x86_64"):
        raise UpdateError(
            "Automatic updates currently support Windows and Linux x64 portable builds."
        )
    client = client or GithubTransport()
    try:
        release = json.loads(_read(client, API, 1024 * 1024, stop))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (403, 429):
            raise UpdateError("GitHub is limiting update checks. Try again later.") from None
        raise UpdateError("GitHub could not be reached. Try checking again later.") from None
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise UpdateError("The latest release does not have a stable version tag.")
    if version_key(tag) <= version_key(current):
        return None
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("The release asset list is invalid.")
    name = (
        "CollectionsStudio-windows-x64.exe" if system == "win32" else "CollectionsStudio-linux-x64"
    )
    binary, sums = _asset(assets, name, tag), _asset(assets, "SHA256SUMS", tag)
    size = binary.get("size")
    if type(size) is not int or not 0 < size <= MAX_BINARY:
        raise UpdateError("The release executable has an invalid size.")
    digest = binary.get("digest") or ""
    if digest and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise UpdateError("The release executable has an invalid checksum.")
    notes = release.get("body") or ""
    return UpdateInfo(
        tag[1:],
        tag,
        str(notes)[:20_000],
        name,
        binary["browser_download_url"],
        size,
        sums["browser_download_url"],
        digest.removeprefix("sha256:").lower(),
    )


def download_update(info, directory, *, client=None, stop=None, progress=None):
    client = client or GithubTransport()
    sums = _read(client, info.checksums_url, 64 * 1024, stop).decode("utf-8", errors="strict")
    matches = []
    for line in sums.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if match and match.group(2) == info.asset_name:
            matches.append(match.group(1).lower())
    if len(matches) != 1 or (info.digest and info.digest != matches[0]):
        raise UpdateError(
            "Release checksums are missing, ambiguous or inconsistent. Nothing was installed."
        )
    expected = matches[0]
    partial, candidate = Path(directory) / "download.part", Path(directory) / "download"
    try:
        checksum, size = hashlib.sha256(), 0
        with client.open(info.asset_url) as response, partial.open("xb") as output:
            while True:
                if stop is not None:
                    _check_cancel(stop)
                block = response.read(256 * 1024)
                if not block:
                    break
                size += len(block)
                if size > info.size:
                    raise UpdateError("The update download exceeds its declared size.")
                output.write(block)
                checksum.update(block)
                if progress is not None:
                    progress(
                        f"Downloading update: {size / 1024**2:.1f} / {info.size / 1024**2:.1f} MiB"
                    )
            output.flush()
            import os

            os.fsync(output.fileno())
        if size != info.size or checksum.hexdigest() != expected:
            raise UpdateError(
                "The update download failed checksum verification. Nothing was installed."
            )
        with partial.open("rb") as stream:
            signature = stream.read(4)
        if not (
            signature == b"\x7fELF"
            if info.asset_name.endswith("linux-x64")
            else signature[:2] == b"MZ"
        ):
            raise UpdateError("The downloaded file is not the expected executable type.")
        if stop is not None:
            _check_cancel(stop)
        partial.replace(candidate)
        return expected
    finally:
        partial.unlink(missing_ok=True)
