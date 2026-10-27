import hashlib
import io
import json
import os
import threading
import urllib.error
import urllib.request
import urllib.response
import zipfile
from email.message import Message
from pathlib import Path

import pytest

from tools import beatmap_downloads as downloads
from tools.beatmap_downloads import Downloader, DownloadError, Mirror, inspect_archive


def difficulty(name, identifier):
    return (
        f"osu file format v14\n[General]\nMode:0\n[Metadata]\nTitle:Song\n"
        f"Artist:Artist\nVersion:{name}\nBeatmapID:{identifier}\nBeatmapSetID:7\n"
    ).encode()


DATA_A, DATA_B = difficulty("Hard", 70), difficulty("Extra", 71)
A, B = (hashlib.md5(data, usedforsecurity=False).hexdigest() for data in (DATA_A, DATA_B))


def archive_bytes(members=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in (
            members or {"hard.osu": DATA_A, "extra.osu": DATA_B, "audio.mp3": b"audio"}
        ).items():
            archive.writestr(name, data)
    return output.getvalue()


def lookup(checksum=A):
    return json.dumps(
        {
            "id": 7,
            "title": "Song",
            "artist": "Artist",
            "beatmaps": [
                {"id": 70, "checksum": checksum, "version": "Hard", "mode": "osu"},
            ],
        }
    ).encode()


ONE = Mirror("One", "https://one.test/d/{id}", "https://one.test/md5/{md5}", "set")
TWO = Mirror("Two", "https://two.test/d/{id}", "https://two.test/md5/{md5}", "set")
THREE = Mirror("Three", "https://three.test/d/{id}")
HINAI = next(mirror for mirror in downloads.MIRRORS if mirror.name == "Hinamizawa")


def hinai_lookup(checksum=A, parent=7):
    return json.dumps(
        {
            "SetID": 7,
            "Title": "Song",
            "Artist": "Artist",
            "ChildrenBeatmaps": [
                {
                    "FileMD5": checksum,
                    "ParentSetID": parent,
                    "BeatmapID": 70,
                    "DiffName": "Hard",
                    "Mode": 0,
                },
            ],
        }
    ).encode()


class Response(io.BytesIO):
    def __init__(self, body, headers=None, on_read=None):
        super().__init__(body)
        self.headers = headers or {"Content-Length": str(len(body))}
        self.on_read = on_read

    def read1(self, size):
        if self.on_read:
            self.on_read()
        return self.read(size)


class Client:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def open(self, url):
        self.calls.append(url)
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return value() if callable(value) else Response(value)


def engine(routes, mirrors=(ONE, TWO, THREE)):
    return Downloader(mirrors, Client(routes), interval=0)


def test_lookup_and_download_fallback_verifies_exact_md5_and_deduplicates_sets(tmp_path):
    worker = engine(
        {
            f"https://one.test/md5/{A}": urllib.error.URLError("offline"),
            f"https://two.test/md5/{A}": lookup(),
            "https://one.test/d/7": b"<html>upstream error</html>",
            "https://two.test/d/7": archive_bytes({"wrong.osu": difficulty("Old", 99)}),
            "https://three.test/d/7": archive_bytes(),
        }
    )
    result = worker.run([A, A.upper(), B], tmp_path)
    assert [item["state"] for item in result["results"]] == ["Ready", "Ready"]
    assert result["requested"] == 2
    assert inspect_archive(tmp_path / "7.osz").keys() == {A, B}
    assert len(worker.client.calls) == 5
    assert len(result["results"][0]["attempts"]) == 3
    assert not list(tmp_path.glob("*.part"))
    assert (
        json.loads(Path(result["report_path"]).read_text())["results"][1]["details"]["Difficulty"]
        == "Extra"
    )


def test_existing_downloads_are_reused_without_network(tmp_path):
    first = engine({f"https://one.test/md5/{A}": lookup(), "https://one.test/d/7": archive_bytes()})
    first.run([A], tmp_path)
    offline = engine({})
    report = offline.run([B], tmp_path)
    assert report["results"][0]["state"] == "Ready"
    assert not offline.client.calls
    assert (tmp_path / "7.osz").stat().st_mode & 0o777 == 0o600


def test_resume_restores_completed_maps_without_opening_any_zip_or_using_network(
    tmp_path, monkeypatch
):
    first = engine(
        {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    )
    first.run([A, B], tmp_path)
    monkeypatch.setattr(
        downloads,
        "inspect_archive",
        lambda *_args, **_kwargs: pytest.fail(
            "An unchanged completed archive must not be reopened"
        ),
    )
    progress = downloads.load_download_progress(tmp_path)
    assert set(progress["completed"]) == {A, B}
    assert all(item["reused"] for item in progress["completed"].values())
    resumed = engine({}, (ONE,))
    result = resumed.run(progress["hashes"], tmp_path)
    assert not resumed.client.calls
    assert all(
        item["state"] == "Ready" and item["verification"] == "unchanged"
        for item in result["results"]
    )
    record = json.loads((tmp_path / downloads.INDEX_FILE).read_text())
    assert record["version"] == 2 and record["archives"]["7.osz"]["maps"][A]["Title"] == "Song"


def test_legacy_index_is_verified_once_then_upgraded_to_completion_records(tmp_path, monkeypatch):
    engine(
        {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    ).run([A, B], tmp_path)
    path = tmp_path / downloads.INDEX_FILE
    record = json.loads(path.read_text())
    path.write_text(json.dumps({"version": 1, "hashes": record["hashes"]}))
    assert not downloads.load_download_progress(tmp_path)["completed"]
    inspected = []
    original = downloads.inspect_archive

    def track(path, stop=None):
        inspected.append(path)
        return original(path, stop)

    monkeypatch.setattr(downloads, "inspect_archive", track)
    resumed = engine({}, (ONE,))
    resumed.run([A, B], tmp_path)
    assert len(inspected) == 1 and not resumed.client.calls
    assert len(downloads.load_download_progress(tmp_path)["completed"]) == 2
    resumed.run([A, B], tmp_path)
    assert len(inspected) == 1


def test_changed_archive_with_preserved_size_and_mtime_is_rechecked(tmp_path, monkeypatch):
    routes = {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}
    engine(routes, (ONE,)).run([A], tmp_path)
    path = tmp_path / "7.osz"
    previous = path.stat()
    path.write_bytes(b"x" * previous.st_size)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert not downloads.load_download_progress(tmp_path)["completed"]
    inspected = []
    original = downloads.inspect_archive

    def track(path, stop=None):
        inspected.append(path)
        return original(path, stop)

    monkeypatch.setattr(downloads, "inspect_archive", track)
    result = engine(routes, (ONE,)).run([A], tmp_path)
    assert result["results"][0]["state"] == "Ready" and inspected
    assert path.read_bytes() == b"x" * previous.st_size
    assert result["results"][0]["file"] != str(path)


@pytest.mark.parametrize("damage", ["deleted", "symlink", "bad_metadata", "bad_signature"])
def test_completion_records_never_skip_missing_changed_or_invalid_files(tmp_path, damage):
    engine(
        {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    ).run([A], tmp_path)
    path = tmp_path / "7.osz"
    index = tmp_path / downloads.INDEX_FILE
    record = json.loads(index.read_text())
    if damage == "deleted":
        path.unlink()
    elif damage == "symlink":
        if os.name == "nt":
            pytest.skip("Creating symbolic links may require Windows developer mode")
        moved = tmp_path / "other.osz"
        path.rename(moved)
        path.symlink_to(moved)
    elif damage == "bad_metadata":
        record["archives"][path.name]["maps"][A]["Title"] = {"unexpected": "object"}
        index.write_text(json.dumps(record))
    else:
        record["archives"][path.name]["signature"]["size"] += 1
        index.write_text(json.dumps(record))
    assert not downloads.load_download_progress(tmp_path)["completed"]


def test_corrupt_existing_file_is_preserved_and_gets_new_verified_replacement(tmp_path):
    (tmp_path / "7.osz").write_bytes(b"existing corrupt file")
    worker = engine(
        {f"https://one.test/md5/{A}": lookup(), "https://one.test/d/7": archive_bytes()}
    )
    report = worker.run([A], tmp_path)
    assert report["results"][0]["state"] == "Ready"
    assert (tmp_path / "7.osz").read_bytes() == b"existing corrupt file"
    assert Path(report["results"][0]["file"]).name != "7.osz"


def test_cancel_removes_partial_download_and_keeps_no_unverified_output(tmp_path):
    stop = threading.Event()
    worker = engine(
        {
            f"https://one.test/md5/{A}": lookup(),
            "https://one.test/d/7": lambda: Response(archive_bytes(), on_read=stop.set),
        }
    )
    report = worker.run([A, B], tmp_path, stop=stop)
    assert report["cancelled"]
    assert report["results"][0]["state"] == "Cancelled"
    assert not list(tmp_path.glob("*.osz"))
    assert not list(tmp_path.glob("*.part"))


def test_cancel_and_fresh_process_resume_preserves_completed_and_untouched_maps(tmp_path):
    data_c = difficulty("Insane", 72)
    checksum_c = hashlib.md5(data_c, usedforsecurity=False).hexdigest()
    hashes = [A, B, checksum_c]
    stop = threading.Event()
    first = engine(
        {
            ONE.lookup.format(md5=A): lookup(),
            ONE.lookup.format(md5=B): lookup(B),
            ONE.download.format(id=7): lambda: Response(
                archive_bytes({"hard.osu": DATA_A})
                if not (tmp_path / "7.osz").exists()
                else archive_bytes({"extra.osu": DATA_B}),
                on_read=stop.set if (tmp_path / "7.osz").exists() else None,
            ),
        },
        (ONE,),
    )
    paused = first.run(hashes, tmp_path, stop=stop)
    assert paused["cancelled"]
    assert [item["state"] for item in paused["results"]] == ["Ready", "Cancelled"]
    saved = downloads.read_download_queue(tmp_path)
    assert saved["hashes"] == hashes  # Includes the third, never-started map.
    assert saved["mirrors"] == ["One"]
    assert Path(paused["queue_path"]).stat().st_mode & 0o777 == 0o600
    original_archive = (tmp_path / "7.osz").read_bytes()
    assert not list(tmp_path.glob("*.part"))

    resumed = engine(
        {
            ONE.lookup.format(md5=B): lookup(B),
            ONE.download.format(id=7): archive_bytes({"extra.osu": DATA_B, "insane.osu": data_c}),
        },
        (ONE,),
    )
    result = resumed.run(saved["hashes"], tmp_path)
    assert [item["state"] for item in result["results"]] == ["Ready"] * 3
    assert resumed.client.calls == [ONE.lookup.format(md5=B), ONE.download.format(id=7)]
    assert (tmp_path / "7.osz").read_bytes() == original_archive
    assert len(list(tmp_path.glob("*.osz"))) == 2


def test_queue_is_saved_before_network_and_keeps_prior_batches(tmp_path):
    stop = threading.Event()

    def interrupted_lookup():
        assert downloads.read_download_queue(tmp_path)["hashes"] == [A]
        return Response(lookup(), on_read=stop.set)

    first = engine({ONE.lookup.format(md5=A): interrupted_lookup}, (ONE,))
    assert first.run([A], tmp_path, stop=stop)["cancelled"]
    second = engine(
        {TWO.lookup.format(md5=B): lookup(B), TWO.download.format(id=7): archive_bytes()},
        (TWO,),
    )
    second.run([B, B.upper()], tmp_path)
    saved = downloads.read_download_queue(tmp_path)
    assert saved["hashes"] == [A, B]
    assert saved["mirrors"] == ["Two"]


@pytest.mark.parametrize("damage", ["deleted", "corrupt"])
def test_resume_rechecks_saved_archive_and_recovers_missing_or_corrupt_files(tmp_path, damage):
    routes = {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}
    engine(routes, (ONE,)).run([A], tmp_path)
    path = tmp_path / "7.osz"
    if damage == "deleted":
        path.unlink()
    else:
        path.write_bytes(b"corrupt completed file")
    resumed = engine(routes, (ONE,))
    result = resumed.run(downloads.read_download_queue(tmp_path)["hashes"], tmp_path)
    assert result["results"][0]["state"] == "Ready"
    assert resumed.client.calls == [ONE.lookup.format(md5=A), ONE.download.format(id=7)]
    assert A in inspect_archive(result["results"][0]["file"])
    if damage == "corrupt":
        assert path.read_bytes() == b"corrupt completed file"


@pytest.mark.parametrize(
    "body",
    [
        b"{incomplete",
        json.dumps({"version": 2, "hashes": [A], "mirrors": ["One"]}).encode(),
        json.dumps({"version": 1, "hashes": ["bad"], "mirrors": ["One"]}).encode(),
        json.dumps({"version": 1, "hashes": [A], "mirrors": "One"}).encode(),
    ],
)
def test_invalid_queue_is_preserved_without_starting_downloads(tmp_path, body):
    path = tmp_path / downloads.QUEUE_FILE
    path.write_bytes(body)
    worker = engine({})
    with pytest.raises(DownloadError, match="saved download queue"):
        worker.run([A], tmp_path)
    assert path.read_bytes() == body
    assert not worker.client.calls


def test_rate_limit_cooldown_respects_retry_after_and_uses_other_mirror(tmp_path):
    limited = urllib.error.HTTPError(
        "https://one.test", 429, "slow down", {"Retry-After": "600"}, None
    )
    worker = engine(
        {
            f"https://one.test/md5/{A}": limited,
            f"https://two.test/md5/{A}": lookup(),
            "https://two.test/d/7": archive_bytes(),
        }
    )
    report = worker.run([A], tmp_path)
    assert report["results"][0]["state"] == "Ready"
    assert len([url for url in worker.client.calls if "one.test" in url]) == 1
    assert worker.cooldowns["One"] > worker.now() + 590


def test_unresolvable_or_wrong_revision_is_reported_without_changing_hash(tmp_path):
    worker = engine(
        {
            f"https://one.test/md5/{A}": lookup(),
            "https://one.test/d/7": archive_bytes({"new.osu": difficulty("New", 80)}),
        },
        (ONE,),
    )
    report = worker.run([A], tmp_path)
    assert report["results"][0]["hash"] == A
    assert report["results"][0]["state"] == "Failed"
    assert "different revision" in report["results"][0]["attempts"][0]["error"]
    assert not list(tmp_path.glob("*.osz"))


def test_lookup_must_match_requested_hash_before_download(tmp_path):
    worker = engine({f"https://one.test/md5/{A}": lookup(B)}, (ONE,))
    report = worker.run([A], tmp_path)
    assert report["results"][0]["state"] == "Failed"
    assert worker.client.calls == [f"https://one.test/md5/{A}"]


@pytest.mark.parametrize(
    "members",
    [
        {"../bad.osu": DATA_A},
        {"/bad.osu": DATA_A},
        {"C:\\bad.osu": DATA_A},
        {"readme.txt": b"hello"},
        {"bad.osu": b"Not a beatmap"},
    ],
)
def test_reject_unsafe_or_non_beatmap_archives(tmp_path, members):
    path = tmp_path / "test.osz"
    path.write_bytes(archive_bytes(members))
    with pytest.raises(DownloadError):
        inspect_archive(path)


def test_crc_error_in_resource_is_rejected(tmp_path):
    body = archive_bytes().replace(b"audio", b"AUDIO")
    path = tmp_path / "crc.osz"
    path.write_bytes(body)
    with pytest.raises(DownloadError, match="corrupt"):
        inspect_archive(path)


def test_expanded_and_download_size_limits(tmp_path, monkeypatch):
    path = tmp_path / "limit.osz"
    path.write_bytes(archive_bytes())
    monkeypatch.setattr(downloads, "MAX_ARCHIVE", 10)
    with pytest.raises(DownloadError, match="512"):
        inspect_archive(path)
    monkeypatch.setattr(downloads, "MAX_ARCHIVE", 10000)
    monkeypatch.setattr(downloads, "MAX_EXPANDED", 10)
    with pytest.raises(DownloadError, match="expanded"):
        inspect_archive(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://mirror.test/d/7",
        "https://user:pass@mirror.test/d/7",
        "https://127.0.0.1/d/7",
        "https://localhost/d/7",
    ],
)
def test_reject_insecure_or_credential_redirects(url):
    with pytest.raises(DownloadError):
        downloads.checked_url(url)


@pytest.mark.parametrize("name", ["Sayobot", "Nekoha", "Beatconnect", "osu!dl", "Hinamizawa"])
def test_each_new_archive_source_publishes_only_a_verified_exact_md5(tmp_path, name):
    mirror = next(item for item in downloads.MIRRORS if item.name == name)
    mirrors = (HINAI,) if mirror == HINAI else (mirror, HINAI)
    routes = {
        HINAI.lookup.format(md5=A): hinai_lookup(A.upper()),
        mirror.download.format(id=7): archive_bytes(),
    }
    worker = engine(routes, mirrors)
    result = worker.run([A], tmp_path)
    assert result["results"][0]["state"] == "Ready"
    assert worker.client.calls == [HINAI.lookup.format(md5=A), mirror.download.format(id=7)]
    assert A in inspect_archive(tmp_path / "7.osz")


@pytest.mark.parametrize("checksum,parent", [(B, 7), (A, 8)])
def test_hinai_requires_matching_md5_and_consistent_parent_set(tmp_path, checksum, parent):
    worker = engine({HINAI.lookup.format(md5=A): hinai_lookup(checksum, parent)}, (HINAI,))
    result = worker.run([A], tmp_path)
    assert result["results"][0]["state"] == "Failed"
    assert len(worker.client.calls) == 1
    assert not list(tmp_path.glob("*.osz"))


@pytest.mark.parametrize("children", [None, {}, [], [None], ["bad"]])
def test_hinai_incomplete_lookup_fails_without_partial_download(tmp_path, children):
    document = json.loads(hinai_lookup())
    document["ChildrenBeatmaps"] = children
    worker = engine({HINAI.lookup.format(md5=A): json.dumps(document).encode()}, (HINAI,))
    result = worker.run([A], tmp_path)
    assert result["results"][0]["state"] == "Failed"
    assert not list(tmp_path.glob("*.osz"))


def test_all_eight_mirrors_fall_through_to_last_verified_archive(tmp_path):
    mirrors = downloads.MIRRORS
    routes = {
        mirror.lookup.format(md5=A): urllib.error.URLError("unavailable")
        for mirror in mirrors
        if mirror.lookup
    }
    routes[HINAI.lookup.format(md5=A)] = hinai_lookup()
    for mirror in mirrors:
        routes[mirror.download.format(id=7)] = lambda: Response(
            b"<html>challenge</html>", {"Content-Type": "text/html"}
        )
    routes[HINAI.download.format(id=7)] = archive_bytes()
    worker = engine(routes, mirrors)
    result = worker.run([A], tmp_path)
    assert result["results"][0]["state"] == "Ready"
    failed = result["results"][0]["attempts"]
    assert [item["mirror"] for item in failed if item["stage"] == "download"] == [
        mirror.name for mirror in mirrors[:-1]
    ]
    assert worker.client.calls[-1] == HINAI.download.format(id=7)
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("kind", ["text/html", "application/json"])
def test_html_challenge_or_json_handoff_is_skipped_for_an_archive(tmp_path, kind):
    worker = engine(
        {
            f"https://one.test/md5/{A}": lookup(),
            "https://one.test/d/7": lambda: Response(b"not an archive", {"Content-Type": kind}),
            "https://two.test/d/7": archive_bytes(),
        },
        (ONE, TWO),
    )
    result = worker.run([A], tmp_path)
    assert result["results"][0]["state"] == "Ready"
    assert "instead of an archive" in result["results"][0]["attempts"][0]["error"]


def response_for(request, body, status=200, headers=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    response = urllib.response.addinfourl(io.BytesIO(body), message, request.full_url, status)
    response.msg = "OK" if status == 200 else "Found"
    return response


def test_osudl_presigned_https_redirect_downloads_and_verifies_archive(tmp_path):
    mirror = next(item for item in downloads.MIRRORS if item.name == "osu!dl")
    signed = "https://storage.r2.cloudflarestorage.com/maps/7.osz?X-Amz-Signature=fixture&X-Amz-Expires=60"
    calls = []

    class Transport(urllib.request.HTTPSHandler):
        def https_open(self, request):
            calls.append(request.full_url)
            assert request.get_header("Authorization") is None
            assert request.get_header("Cookie") is None
            if request.full_url == HINAI.lookup.format(md5=A):
                return response_for(
                    request, hinai_lookup(), headers={"Content-Type": "application/json"}
                )
            if request.full_url == mirror.download.format(id=7):
                return response_for(request, b"", 302, {"Location": signed})
            assert request.full_url == signed  # Preserve the complete signature query.
            return response_for(
                request, archive_bytes(), headers={"Content-Type": "application/octet-stream"}
            )

    client = downloads.HttpClient()
    client.opener = urllib.request.build_opener(Transport(), downloads.HttpsRedirects())
    result = Downloader((mirror, HINAI), client, interval=0).run([A], tmp_path)
    assert result["results"][0]["state"] == "Ready"
    assert calls == [HINAI.lookup.format(md5=A), mirror.download.format(id=7), signed]
    assert A in inspect_archive(tmp_path / "7.osz")


@pytest.mark.parametrize(
    "target",
    [
        "http://public.test/file.osz",
        "https://127.0.0.1/file.osz",
        "https://user:pass@public.test/file.osz",
    ],
)
def test_archive_redirect_handler_still_rejects_unsafe_destinations(target):
    calls = []

    class Transport(urllib.request.HTTPSHandler):
        def https_open(self, request):
            calls.append(request.full_url)
            return response_for(request, b"", 302, {"Location": target})

    client = downloads.HttpClient()
    client.opener = urllib.request.build_opener(Transport(), downloads.HttpsRedirects())
    with pytest.raises(DownloadError):
        client.open("https://osudl.org/s/7")
    assert calls == ["https://osudl.org/s/7"]
