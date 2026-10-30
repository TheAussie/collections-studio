import io
import json
import threading
import urllib.error
from types import SimpleNamespace

import pytest

from tools.beatmap_downloads import Cancelled, Downloader, DownloadError, Mirror
from tools.osu_credentials import CredentialError, CredentialStore
from tools.osu_lookup import NoRedirect, OfficialLookup

HASH = "a" * 32
SECRET = "synthetic-only-secret"


class Clock:
    def __init__(self):
        self.now = 100.0
        self.waits = []

    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
        return False

    def is_set(self):
        return False


class Opener:
    def __init__(self, item=None):
        self.item = item or {
            "id": 12,
            "checksum": HASH,
            "beatmapset_id": 3,
            "status": "graveyard",
            "version": "Old difficulty",
            "mode_int": 0,
            "beatmapset": {"id": 3, "title": "Map", "artist": "Artist"},
        }
        self.calls = []
        self.error = None

    def open(self, request, timeout):
        self.calls.append(request)
        assert timeout == 10 and request.full_url.startswith("https://osu.ppy.sh/")
        if request.full_url.endswith("/oauth/token"):
            return io.BytesIO(
                json.dumps({"access_token": "fake-token", "expires_in": 3600}).encode()
            )
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.item).encode())


def test_graveyard_exact_hash_token_rate_limit_and_cache():
    clock, opener = Clock(), Opener()
    lookup = OfficialLookup(lambda: ("123", SECRET), opener=opener, now=lambda: clock.now)
    result = lookup.resolve(HASH, clock)
    assert result[0] == 3 and result[1]["BeatmapId"] == 12
    assert result[1]["Difficulty"] == "Old difficulty"
    assert len(opener.calls) == 2 and clock.waits == [pytest.approx(1.05)]
    assert "scope=public" in opener.calls[0].data.decode()
    assert "Authorization" not in opener.calls[0].headers
    assert opener.calls[1].headers["Authorization"] == "Bearer fake-token"
    assert SECRET not in opener.calls[1].full_url
    assert lookup.resolve(HASH, clock) == result and len(opener.calls) == 2


@pytest.mark.parametrize(
    "changed",
    [{"checksum": "b" * 32}, {"id": None}, {"beatmapset_id": None}, {"beatmapset": {"id": 9}}],
)
def test_rejects_wrong_hash_or_inconsistent_identity(changed):
    opener, clock = Opener(), Clock()
    opener.item.update(changed)
    with pytest.raises(DownloadError):
        OfficialLookup(lambda: ("123", SECRET), opener=opener, now=lambda: clock.now).resolve(
            HASH, clock
        )


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_http_failure_redacts_secrets_and_authentication_or_rate_limit_does_not_hammer(status):
    opener, clock = Opener(), Clock()
    opener.error = urllib.error.HTTPError(
        "https://osu.ppy.sh/api/v2/beatmaps/lookup", status, SECRET, {"Retry-After": "120"}, None
    )
    lookup = OfficialLookup(lambda: ("123", SECRET), opener=opener, now=lambda: clock.now)
    with pytest.raises(DownloadError) as error:
        lookup.resolve(HASH, clock)
    assert SECRET not in str(error.value)
    if status in (401, 403, 429):
        with pytest.raises(DownloadError):
            lookup.resolve("b" * 32, clock)
        assert len(opener.calls) == 2


def test_cancel_and_redirect_never_send_credentials_elsewhere():
    stop = threading.Event()
    stop.set()
    opener = Opener()
    with pytest.raises(Cancelled):
        OfficialLookup(lambda: pytest.fail("No credentials on cancel"), opener=opener).resolve(
            HASH, stop
        )
    assert opener.calls == []
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test") is None


def test_engine_official_provider_is_optional_and_only_used_after_mirror_failure():
    clock = Clock()
    opener = Opener()
    downloader = Downloader(mirrors=())
    events = []
    attempts = []
    with pytest.raises(DownloadError):
        downloader._resolve(HASH, clock, events.append, attempts)
    downloader.official_lookup = OfficialLookup(
        lambda: ("123", SECRET), opener=opener, now=lambda: clock.now
    )
    assert downloader._resolve(HASH, clock, events.append, attempts)[0] == 3
    assert events[-1]["kind"] == "metadata" and SECRET not in json.dumps(events + attempts)
    downloader.mirrors = (
        Mirror("Fixture", "https://fixture.test/{id}", "https://fixture.test/{md5}", "set"),
    )
    downloader._open = lambda *_: io.BytesIO(
        json.dumps(
            {"id": 9, "title": "Mirror map", "beatmaps": [{"checksum": HASH, "id": 13}]}
        ).encode()
    )
    downloader.official_lookup = SimpleNamespace(
        resolve=lambda *_: pytest.fail("Mirrors remain first")
    )
    assert downloader._resolve(HASH, clock, events.append, attempts)[0] == 9


def test_native_store_uses_stdin_not_arguments_and_never_plaintext_fallback(monkeypatch):
    import tools.osu_credentials as module

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/secret-tool")
    calls = []
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/old-bundle")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/lib")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(["123", SECRET]), stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    store = CredentialStore()
    assert store.save("123", SECRET) == ("123", SECRET)
    assert SECRET not in str(calls[0][0]) and SECRET in calls[0][1]["input"]
    assert calls[0][1]["env"]["LD_LIBRARY_PATH"] == "/system/lib"
    assert store.load() == ("123", SECRET)
    store.delete()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    with pytest.raises(CredentialError, match="session"):
        store.save("123", SECRET)


def test_appimage_cannot_target_extracted_portable_binary(monkeypatch):
    import tools.update_install as install

    monkeypatch.setattr(install.sys, "frozen", True, raising=False)
    monkeypatch.setenv("COLLECTIONS_STUDIO_APPIMAGE", "1")
    with pytest.raises(ValueError, match="AppImage"):
        install.portable_target()


def test_session_only_dialog_never_writes_secret_to_settings(qt_app, tmp_path):
    import time

    from PySide6.QtCore import QSettings

    from tools.qt_collection_studio import StudioWindow
    from tools.qt_osu_credentials import OsuCredentialsDialog

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    view = StudioWindow(settings=settings)
    store = SimpleNamespace(
        save=lambda *_: pytest.fail("Session credentials must not be saved"),
        load=lambda: pytest.fail("No vault read needed"),
    )
    dialog = OsuCredentialsDialog(view, store=store)
    dialog.client_id.setText("123")
    dialog.secret.setText(SECRET)
    dialog.start("session")
    deadline = time.monotonic() + 3
    while dialog.job and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    assert view.osu_api_credentials == ("123", SECRET)
    settings.sync()
    assert SECRET not in (tmp_path / "settings.ini").read_text()
    assert settings.value("osu-api/client-id") == "123"
    view.close()
    view.pool.waitForDone(5000)
    qt_app.processEvents()
