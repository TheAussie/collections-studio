import json
import sys
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa:E402

from tests.test_qt_studio import populate  # noqa:E402
from tests.test_qt_studio import window as window
from tools import linux_install  # noqa:E402
from tools.qt_install_dialog import InstallationDialog  # noqa:E402

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux desktop integration")


def finish(dialog):
    deadline = time.monotonic() + 5
    while dialog.job is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert dialog.job is None
    QApplication.processEvents()


def test_install_uninstall_cancel_and_reopen_keep_collection_work(window, tmp_path, monkeypatch):
    populate(window)
    before = (
        json.dumps(window.workspace.document, sort_keys=True)
        if hasattr(window.workspace, "document")
        else json.dumps(window.workspace.plan(), sort_keys=True)
    )
    source = tmp_path / "downloaded app"
    source.write_bytes(b"\x7fELF synthetic app")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    layout = linux_install.Layout(tmp_path / "app data", desktop)
    artifact = linux_install.Artifact(source, "binary")
    dialog = InstallationDialog(window, layout=layout, artifact=artifact)
    window._open_dialog("install_dialog", dialog)
    assert not window.tools_button.isEnabled()
    assert not dialog.uninstall_button.isEnabled()
    dialog.desktop.setChecked(True)
    dialog.install_button.click()
    assert not dialog.can_close()
    finish(dialog)
    assert layout.binary.exists() and layout.icon.exists() and layout.desktop.exists()
    assert dialog.uninstall_button.isEnabled()
    assert not window._closed
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
    dialog.uninstall_button.click()
    assert dialog.job is None and layout.binary.exists()
    dialog.reject()
    QApplication.processEvents()
    assert window.install_dialog is None and window.tools_button.isEnabled()
    reopened = InstallationDialog(window, layout=layout, artifact=artifact)
    window._open_dialog("install_dialog", reopened)
    assert reopened.record["version"] == window.version
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    reopened.uninstall_button.click()
    finish(reopened)
    assert not layout.binary.exists() and not layout.launcher.exists()
    assert "Uninstalled" in reopened.status.text()
    assert not window._closed and source.exists()
    after = (
        json.dumps(window.workspace.document, sort_keys=True)
        if hasattr(window.workspace, "document")
        else json.dumps(window.workspace.plan(), sort_keys=True)
    )
    assert before == after
    reopened.reject()
    QApplication.processEvents()


def test_source_mode_explains_disabled_install_but_has_no_side_effects(window, tmp_path):
    layout = linux_install.Layout(tmp_path / "empty app data")
    dialog = InstallationDialog(window, layout=layout)
    assert not dialog.install_button.isEnabled()
    assert not dialog.uninstall_button.isEnabled()
    assert "Source checkouts" in dialog.status.text()
    dialog.reject()
    QApplication.processEvents()
    assert not layout.data.exists()


def test_current_window_waits_for_installer_without_closing(window, tmp_path):
    layout = linux_install.Layout(tmp_path / "data")
    dialog = InstallationDialog(window, layout=layout)
    window._open_dialog("install_dialog", dialog)
    dialog.job = object()
    window.close()
    QApplication.processEvents()
    assert not window._closed and not dialog._closed
    dialog.job = None
    dialog.reject()
    QApplication.processEvents()


def test_uninstalling_the_running_installed_file_keeps_window_and_disables_reinstall(
    window, tmp_path, monkeypatch
):
    source = tmp_path / "original download"
    source.write_bytes(b"\x7fELF fake packaged app")
    layout = linux_install.Layout(tmp_path / "installed data")
    linux_install.install(layout, linux_install.Artifact(source, "binary"), window.version)
    dialog = InstallationDialog(
        window, layout=layout, artifact=linux_install.Artifact(layout.binary, "binary")
    )
    window._open_dialog("install_dialog", dialog)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog.uninstall_button.click()
    finish(dialog)
    assert not window._closed and not dialog.install_button.isEnabled()
    assert source.exists() and not layout.binary.exists()
    dialog.reject()
    QApplication.processEvents()
