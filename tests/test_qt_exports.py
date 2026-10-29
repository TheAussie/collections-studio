import time
from copy import deepcopy

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from tests.qt_support import dispose  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_collection_studio import StudioWindow  # noqa: E402
from tools.qt_export_dialog import ExportDialog  # noqa: E402
from tools.qt_models import IDENTITY_ROLE  # noqa: E402
from tools.stable_collections import read_stable  # noqa: E402

A, B = "a" * 32, "b" * 32


@pytest.fixture
def app(qt_app, tmp_path, monkeypatch):
    view = StudioWindow(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    view.workspace = Workspace(
        {
            "Format": "stable",
            "SourceRealmSha256": "",
            "Collections": [
                {"Id": "one", "Name": "Alpha", "Hashes": [A]},
                {"Id": "two", "Name": "Beta 練習", "Hashes": [A, B]},
                {"Id": "empty", "Name": "Empty", "Hashes": []},
            ],
        },
        "",
    )
    view.refresh_collections()
    view.show()
    qt_app.processEvents()
    view.errors = []
    monkeypatch.setattr(view, "error", view.errors.append)
    yield view
    view.pool.waitForDone(10000)
    qt_app.processEvents()
    view.workspace._baseline = view.workspace.plan()["Collections"]
    view.close()
    qt_app.processEvents()
    dispose(view)


def check(dialog, identifier, enabled=True):
    for row in range(dialog.model.rowCount()):
        index = dialog.model.index(row, 0)
        if index.data(IDENTITY_ROLE) == identifier:
            assert dialog.model.setData(
                index,
                Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked,
                Qt.ItemDataRole.CheckStateRole,
            )
            return
    pytest.fail("Missing fixture collection")


def test_all_and_checked_modes_keep_hidden_choices_and_toggle_back_without_losing_checks(app):
    dialog = ExportDialog(app)
    assert dialog.model.selected_ids() == {"one", "two", "empty"}
    assert not dialog.table.isEnabled() and dialog.export_button.isEnabled()
    dialog.selected_button.click()
    dialog.clear_button.click()
    assert not dialog.export_button.isEnabled()
    check(dialog, "one")
    dialog.search.setText("Beta")
    assert dialog.proxy.rowCount() == 1
    check(dialog, "two")
    assert dialog.model.selected_ids() == {"one", "two"}
    assert "2 collections" in dialog.summary.text()
    dialog.all_button.click()
    assert dialog.model.selected_ids() == {"one", "two", "empty"}
    dialog.selected_button.click()
    assert dialog.model.selected_ids() == {"one", "two"}
    dialog.search.clear()
    assert dialog.proxy.rowCount() == 3
    dialog.close()


def test_cancelled_filename_picker_and_existing_file_keep_dialog_and_choices(
    app, monkeypatch, tmp_path
):
    dialog = ExportDialog(app)
    dialog.selected_button.click()
    dialog.clear_button.click()
    check(dialog, "empty")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
    dialog.choose_file()
    assert not dialog.destination and dialog.model.selected_ids() == {"empty"}
    existing = tmp_path / "keep.db"
    existing.write_bytes(b"Keep this")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(existing), ""))
    dialog.choose_file()
    assert not dialog.destination and "already exists" in dialog.status.text()
    assert existing.read_bytes() == b"Keep this"
    dialog.close()
    reopened = ExportDialog(app)
    assert reopened.all_button.isChecked() and len(reopened.model.selected_ids()) == 3
    reopened.close()


@pytest.mark.parametrize("selected", [False, True])
def test_toolbar_export_runs_in_background_and_preserves_editing_session(
    app, monkeypatch, tmp_path, selected
):
    app.workspace.rename("two", "Edited 練習")
    app.refresh_collections()
    before = deepcopy(vars(app.workspace))
    if not selected:
        app.collection_search.setText("Alpha")  # Full export includes hidden sidebar collections.
    target = tmp_path / "export 練習"  # The dialog appends .db.
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(target), ""))

    def accept(dialog):
        if selected:
            dialog.selected_button.click()
            dialog.clear_button.click()
            check(dialog, "two")
            check(dialog, "empty")
        dialog.choose_file()
        return dialog.result()

    monkeypatch.setattr(ExportDialog, "exec", accept)
    assert app.export_button.isEnabled() and app.export_action.isEnabled()
    app.export_button.click()
    assert app.job is not None and app._writing
    assert not app.export_button.isEnabled()
    deadline = time.monotonic() + 5
    while app.job and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.004)
    assert app.job is None and not app.errors
    groups = read_stable(target.with_suffix(".db"))["Collections"]
    assert [g["Name"] for g in groups] == (
        ["Edited 練習", "Empty"] if selected else ["Alpha", "Edited 練習", "Empty"]
    )
    assert vars(app.workspace) == before and app.workspace.dirty and app.workspace.can_undo
    assert "Exported" in app.status.text() and "Verified collection.db" in app.details.toPlainText()
    assert app.export_button.isEnabled()


def test_cancel_export_writes_nothing_and_empty_library_disables_export(app, monkeypatch, tmp_path):
    before = deepcopy(vars(app.workspace))
    monkeypatch.setattr(ExportDialog, "exec", lambda _self: ExportDialog.DialogCode.Rejected)
    app.export_action.trigger()
    assert app.job is None and vars(app.workspace) == before
    assert not list(tmp_path.glob("*.db"))
    app.workspace.collections.clear()
    app.refresh_collections()
    assert not app.export_button.isEnabled() and not app.export_action.isEnabled()
