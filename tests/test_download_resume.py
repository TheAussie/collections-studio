import hashlib
import json
import threading
import urllib.error
from pathlib import Path

import pytest

from tests.test_beatmap_downloads import (
    DATA_A,
    DATA_B,
    ONE,
    A,
    B,
    archive_bytes,
    difficulty,
    engine,
    lookup,
)
from tools import beatmap_downloads as downloads


def checksum(data):
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def test_resume_skips_failed_and_imported_maps_until_explicit_retry(tmp_path, monkeypatch):
    failed_data, pending_data = difficulty("Failed", 72), difficulty("Pending", 73)
    failed, pending = checksum(failed_data), checksum(pending_data)
    stop = threading.Event()
    first = engine(
        {
            ONE.lookup.format(md5=A): lookup(),
            ONE.download.format(id=7): archive_bytes(),
            ONE.lookup.format(md5=failed): urllib.error.URLError("fixture unavailable"),
        },
        (ONE,),
    )

    def pause(event):
        if event["kind"] == "result" and event["hash"] == failed:
            stop.set()

    original = first.run([A, failed, pending], tmp_path, pause, stop)
    assert original["remaining"] == 1 and original["failed"] == 1
    songs = tmp_path / "7 Artist - Song"
    songs.mkdir()
    (songs / "hard.osu").write_bytes(DATA_A)
    (songs / "extra.osu").write_bytes(DATA_B)
    (tmp_path / "7.osz").unlink()  # Simulate osu! consuming this synthetic archive.
    progress = downloads.load_download_progress(tmp_path)
    assert progress["completed"][A]["installed"]
    assert set(progress["failed"]) == {failed}

    second = engine(
        {
            ONE.lookup.format(md5=pending): lookup(pending),
            ONE.download.format(id=7): archive_bytes({"pending.osu": pending_data}),
        },
        (ONE,),
    )
    events = []
    report = second.run([A, failed, pending], tmp_path, events.append)
    assert events[0]["kind"] == "snapshot" and events[0]["remaining"] == 1
    assert second.client.calls == [ONE.lookup.format(md5=pending), ONE.download.format(id=7)]
    assert report["ready"] == 2 and report["failed"] == 1 and report["remaining"] == 0
    assert report["installed"] == 1
    assert (songs / "hard.osu").read_bytes() == DATA_A
    assert not list(tmp_path.glob("download-report-*.json"))
    assert downloads.report_directory() in Path(report["report_path"]).parents

    with monkeypatch.context() as patch:
        patch.setattr(
            downloads.hashlib, "md5", lambda **_kw: pytest.fail("Cached installed map rehashed")
        )
        restored = downloads.load_download_progress(tmp_path)
        assert restored["completed"][A]["installed"]
    retry = engine(
        {
            ONE.lookup.format(md5=failed): lookup(failed),
            ONE.download.format(id=7): archive_bytes({"failed.osu": failed_data}),
        },
        (ONE,),
    )
    final = retry.run([failed], tmp_path, retry_failed=True)
    assert final["ready"] == 1 and final["failed"] == 0
    assert retry.client.calls == [ONE.lookup.format(md5=failed), ONE.download.format(id=7)]


def test_legacy_reports_restore_failures_without_losing_earlier_runs(tmp_path):
    c = "c" * 32
    (tmp_path / downloads.QUEUE_FILE).write_text(
        json.dumps(
            {
                "version": 1,
                "hashes": [A, B, c],
                "mirrors": [ONE.name],
            }
        )
    )
    old = tmp_path / "download-report-original.json"
    old.write_text(
        json.dumps(
            {
                "results": [
                    {"hash": A, "state": "Failed", "message": "fixture failure"},
                    {"hash": B, "state": "Cancelled"},
                ]
            }
        )
    )
    original_bytes = old.read_bytes()
    (tmp_path / "download-report-new.json").write_text(
        json.dumps(
            {
                "results": [
                    {"hash": c, "state": "Failed", "message": "later fixture failure"},
                ]
            }
        )
    )
    progress = downloads.load_download_progress(tmp_path)
    assert set(progress["failed"]) == {A, c}
    assert old.read_bytes() == original_bytes
    worker = engine(
        {ONE.lookup.format(md5=B): lookup(B), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    )
    report = worker.run([A, B, c], tmp_path)
    assert worker.client.calls == [ONE.lookup.format(md5=B), ONE.download.format(id=7)]
    assert report["failed"] == 2 and report["remaining"] == 0
    assert old.read_bytes() == original_bytes
    # The new durable index preserves failures even after old reports are removed.
    old.unlink()
    (tmp_path / "download-report-new.json").unlink()
    assert c in downloads.load_download_progress(tmp_path)["failed"]


@pytest.mark.parametrize("damage", ["wrong_revision", "changed_after_cache"])
def test_imported_folders_require_exact_hash_not_just_set_name(tmp_path, damage):
    engine(
        {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    ).run([A], tmp_path)
    folder = tmp_path / "7 Same set, different revision"
    folder.mkdir()
    path = folder / "hard.osu"
    path.write_bytes(DATA_A if damage == "changed_after_cache" else b"different revision")
    (tmp_path / "7.osz").unlink()
    if damage == "changed_after_cache":
        worker = engine({}, (ONE,))
        assert worker.run([A], tmp_path)["installed"] == 1
        path.write_bytes(b"different revision")
    assert A not in downloads.load_download_progress(tmp_path)["completed"]


def test_reports_have_bounded_retention_outside_downloads_without_touching_queue(tmp_path):
    worker = engine(
        {ONE.lookup.format(md5=A): lookup(), ONE.download.format(id=7): archive_bytes()}, (ONE,)
    )
    first = worker.run([A], tmp_path)
    archive = (tmp_path / "7.osz").read_bytes()
    legacy = tmp_path / "download-report-legacy.json"
    legacy.write_text('{"results": []}')
    for _ in range(12):
        result = engine({}, (ONE,)).run([A], tmp_path)
    folder = downloads.report_directory()
    assert len(list(folder.glob("download-report-*.json"))) == 10
    assert not Path(first["report_path"]).exists()
    assert Path(result["report_path"]).is_file()
    assert (tmp_path / "7.osz").read_bytes() == archive
    assert downloads.read_download_queue(tmp_path)["hashes"] == [A]
    assert legacy.is_file()  # No cleanup of arbitrary existing files in Songs.


def test_resume_does_not_retry_previously_failed_queue_without_network(tmp_path):
    worker = engine({ONE.lookup.format(md5=A): urllib.error.URLError("offline fixture")}, (ONE,))
    assert worker.run([A], tmp_path)["failed"] == 1
    offline = engine({}, (ONE,))
    resumed = offline.run([A], tmp_path)
    assert not offline.client.calls
    assert resumed["failed"] == 1 and resumed["remaining"] == 0


def test_cancelling_preparation_cannot_erase_legacy_failure_history(tmp_path):
    (tmp_path / downloads.QUEUE_FILE).write_text(
        json.dumps(
            {
                "version": 1,
                "hashes": [A, B],
                "mirrors": [ONE.name],
            }
        )
    )
    report = tmp_path / "download-report-old.json"
    report.write_text(json.dumps({"results": [{"hash": A, "state": "Failed"}]}))
    stop = threading.Event()
    stop.set()
    worker = engine({}, (ONE,))
    paused = worker.run([A, B], tmp_path, stop=stop)
    assert paused["cancelled"] and paused["preparation_cancelled"]
    assert not paused["results"] and not worker.client.calls
    restored = downloads.load_download_progress(tmp_path)
    assert set(restored["failed"]) == {A}
