import threading
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from tests.test_app_updates import Client, release  # noqa: E402
from tests.test_qt_studio import wait  # noqa: E402
from tests.test_qt_studio import window as window  # noqa: E402
from tools import qt_collection_studio, qt_update_dialog  # noqa: E402
from tools.app_updates import check_for_update  # noqa: E402
from tools.beatmap_downloads import Cancelled  # noqa: E402
from tools.stable_collections import encode, read_stable  # noqa: E402


def wait_updates(window):
    deadline, settled = time.monotonic() + 8, 0
    while time.monotonic() < deadline:
        QApplication.processEvents()
        dialog = window.update_dialog
        busy = window.job or window.update_check_job or (dialog and dialog.job)
        settled = 0 if busy else settled + 1
        if settled == 3:
            return
        time.sleep(0.005)
    pytest.fail("Update UI did not settle")


def open_update(window):
    window.available_update = check_for_update(
        "0.1.0", client=Client(release()), system="linux", machine="x86_64"
    )
    window.show_updates()
    return window.update_dialog


@pytest.mark.parametrize("choice", ["save", "discard", "cancel"])
def test_unsaved_edits_are_handled_before_download_and_restart(
    window, monkeypatch, tmp_path, choice
):
    source = tmp_path / "collection.db"
    original = encode([{"Name": "Before", "Hashes": []}])
    source.write_bytes(original)
    window.load_path(str(source))
    wait(window)
    window.workspace.rename(window.selected, "After")
    calls = []
    target = tmp_path / "CollectionsStudio"
    target.write_bytes(b"old executable")
    monkeypatch.setattr(qt_update_dialog, "portable_target", lambda: target)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_a: {
            "save": QMessageBox.StandardButton.Save,
            "discard": QMessageBox.StandardButton.Discard,
            "cancel": QMessageBox.StandardButton.Cancel,
        }[choice],
    )

    def download(_info, stage, **_kwargs):
        calls.append("download")
        assert window.workspace.dirty is (choice == "discard")
        return "a" * 64

    monkeypatch.setattr(qt_update_dialog, "download_update", download)
    monkeypatch.setattr(qt_update_dialog, "start_helper", lambda *_a, **_k: calls.append("helper"))
    monkeypatch.setattr(window, "restart_after_update", lambda: calls.append("restart"))
    dialog = open_update(window)
    dialog.install_button.click()
    wait_updates(window)
    assert target.read_bytes() == b"old executable"  # The controller itself never replaces files.
    if choice == "cancel":
        assert not calls and window.workspace.dirty
        dialog.close()
    else:
        assert calls == ["download", "helper", "restart"]
    assert read_stable(source)["Collections"][0]["Name"] == (
        "After" if choice == "save" else "Before"
    )
    assert not window.errors


def test_failed_save_never_starts_download_or_restart(window, monkeypatch, tmp_path):
    source = tmp_path / "collection.db"
    source.write_bytes(encode([{"Name": "Before", "Hashes": []}]))
    window.load_path(str(source))
    wait(window)
    window.workspace.rename(window.selected, "After")
    source.write_bytes(encode([{"Name": "Changed externally", "Hashes": []}]))
    monkeypatch.setattr(qt_update_dialog, "portable_target", lambda: tmp_path / "app")
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(
        qt_update_dialog,
        "download_update",
        lambda *_a, **_k: pytest.fail("No download after a failed save"),
    )
    dialog = open_update(window)
    dialog.install_button.click()
    wait_updates(window)
    assert window.errors and window.workspace.dirty and not window._restarting_for_update
    dialog.close()


def test_download_cancellation_keeps_window_and_executable_running(window, monkeypatch, tmp_path):
    target = tmp_path / "CollectionsStudio"
    target.write_bytes(b"old executable")
    monkeypatch.setattr(qt_update_dialog, "portable_target", lambda: target)
    entered = threading.Event()

    def download(_info, _stage, *, stop, progress):
        entered.set()
        stop.wait(3)
        raise Cancelled()

    monkeypatch.setattr(qt_update_dialog, "download_update", download)
    monkeypatch.setattr(
        qt_update_dialog, "start_helper", lambda *_a, **_k: pytest.fail("No helper after cancel")
    )
    dialog = open_update(window)
    dialog.install_button.click()
    assert entered.wait(2)
    dialog.close_button.click()
    wait_updates(window)
    assert not window._closed and target.read_bytes() == b"old executable"
    assert not list(tmp_path.glob(".collections-studio-update-*"))


def test_background_check_keeps_ui_responsive_and_setting_is_saved(window, monkeypatch):
    info = check_for_update("0.1.0", client=Client(release()), system="linux", machine="x86_64")
    release_wait = threading.Event()

    def check(_version, **_kwargs):
        release_wait.wait(3)
        return info

    monkeypatch.setattr(qt_collection_studio, "check_for_update", check)
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: (beats.append(1), release_wait.set()))
    timer.start(20)
    window.check_updates()
    assert window.open_button.isEnabled()
    wait_updates(window)
    timer.stop()
    assert beats and window.update_notice.isVisible()
    assert window.update_notice.text() == "Update to 0.1.1"
    dialog = open_update(window)
    dialog.automatic.setChecked(False)
    assert window.settings.value("updates/check-on-startup", True, type=bool) is False
    dialog.close()
