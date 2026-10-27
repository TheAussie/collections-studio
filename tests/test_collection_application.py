import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tools import collection_backend, collection_links
from tools.beatmap_downloads import Cancelled
from tools.collection_application import fetch_cancellable_link
from tools.collection_backend import Backend
from tools.stable_collections import scan_songs


def test_link_cancellation_keeps_maps_redirect_policy_and_stops_next_request(monkeypatch):
    stop = threading.Event()
    requests = []

    class Transport:
        def open(self, url):
            requests.append(url)
            stop.set()
            return object()

    monkeypatch.setattr(collection_links, "MapsClient", Transport)

    def fetch(_value, client):
        client.open("https://maps.test/first")
        client.open("https://maps.test/never-requested")

    monkeypatch.setattr(collection_links, "fetch_link", fetch)
    with pytest.raises(Cancelled):
        fetch_cancellable_link("https://maps.test/api/v1/collections/secret", stop)
    assert requests == ["https://maps.test/first"]


def test_cancelled_scan_never_publishes_partial_inventory_cache(tmp_path):
    songs = tmp_path / "Songs 練習"
    songs.mkdir()
    source = songs / "map.osu"
    data = b"osu file format v14\n[Metadata]\nTitle:Fixture\n"
    source.write_bytes(data)
    stop = threading.Event()
    with pytest.raises(Cancelled):
        scan_songs(
            songs, stop=stop, progress=lambda _text: stop.set(), cache_directory=tmp_path / "cache"
        )
    assert source.read_bytes() == data
    assert not list((tmp_path / "cache").glob("*.json"))


def test_frozen_backend_requires_bundled_helper_instead_of_installed_dotnet(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(
        collection_backend.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Must not use an installed SDK"),
    )
    with pytest.raises(RuntimeError, match="bundled Realm helper is missing"):
        Backend().run("inspect", realm_copy="copied.realm")


def test_bundled_helper_passes_unicode_paths_as_arguments_without_shell(monkeypatch, tmp_path):
    helper = (
        tmp_path
        / "backend"
        / ("realm-collection-import.exe" if sys.platform == "win32" else "realm-collection-import")
    )
    helper.parent.mkdir()
    helper.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    calls = []

    def execute(arguments, **options):
        calls.append((arguments, options))
        return subprocess.CompletedProcess(arguments, 0, '{"Collections": []}', "")

    monkeypatch.setattr(collection_backend.subprocess, "run", execute)
    path = Path("folder with spaces") / "練習" / "client.realm"
    assert Backend().run("inspect", realm_copy=path) == {"Collections": []}
    assert calls[0][0] == [str(helper), "inspect", "--realm-copy", str(path)]
    assert calls[0][1]["encoding"] == "utf-8" and not calls[0][1].get("shell")
