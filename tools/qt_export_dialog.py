"""Choose all or checked collections for a single collection.db export."""

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QVBoxLayout,
)

from tools.qt_models import CollectionModel
from tools.qt_style import button, label


class ExportModel(CollectionModel):
    selection_changed = Signal()

    def __init__(self, groups, current_id=None, parent=None):
        super().__init__(parent)
        self.all_collections = True
        self.checked = {current_id} if current_id else set()
        self.replace(groups)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and section == 1
        ):
            return "DIFFICULTIES"
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            return (
                Qt.CheckState.Checked
                if self.all_collections or self.groups[index.row()]["Id"] in self.checked
                else Qt.CheckState.Unchecked
            )
        return super().data(index, role)

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0 and not self.all_collections:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (
            not index.isValid()
            or index.column() != 0
            or self.all_collections
            or role != Qt.ItemDataRole.CheckStateRole
        ):
            return False
        identifier = self.groups[index.row()]["Id"]
        if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
            self.checked.add(identifier)
        else:
            self.checked.discard(identifier)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()
        return True

    def selected_ids(self):
        return {
            group["Id"]
            for group in self.groups
            if self.all_collections or group["Id"] in self.checked
        }

    def changed(self):
        if self.groups:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.groups) - 1, 0),
                [Qt.ItemDataRole.CheckStateRole],
            )
        self.selection_changed.emit()


class ExportDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.destination = ""
        self.setWindowTitle("Export collection.db · Collections Studio")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(740, 660)
        self.setMinimumSize(580, 540)
        self.model = ExportModel(app.workspace.collections, app.selected, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(0)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.sort(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label("Export collections", "heading"))
        intro = label("Save all or chosen collections together in one collection.db.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        if app.workspace.dirty:
            layout.addWidget(label("Includes your unsaved collection edits", "badge"))
        modes = QHBoxLayout()
        self.all_button = button("All collections", lambda: None, "exportMode")
        self.selected_button = button("Choose collections", lambda: None, "exportMode")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for control in (self.all_button, self.selected_button):
            control.setCheckable(True)
            control.setMinimumHeight(56)
            self.mode_group.addButton(control)
            modes.addWidget(control, 1)
        self.all_button.setAccessibleName("Export all collections")
        self.selected_button.setAccessibleName("Choose individual collections to export")
        self.all_button.setToolTip("Include every collection in the export.")
        self.selected_button.setToolTip("Tick the collections you want to include below.")
        self.all_button.setChecked(True)
        layout.addLayout(modes)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search collections")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search collections to export")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        layout.addWidget(self.search)
        self.table = app._table(self.proxy)
        self.table.setAccessibleName("Collections to include in collection.db")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 145)
        layout.addWidget(self.table, 1)
        selection = QHBoxLayout()
        self.select_all_button = button("Check all", lambda: self.check_all(True), "quiet")
        self.clear_button = button("Clear checks", lambda: self.check_all(False), "quiet")
        self.summary = label()
        self.summary.setWordWrap(True)
        selection.addWidget(self.select_all_button)
        selection.addWidget(self.clear_button)
        selection.addStretch()
        selection.addWidget(self.summary)
        layout.addLayout(selection)
        self.status = label("All collections are included, even when searching.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.cancel_button = button("Cancel", self.reject, "quiet")
        self.export_button = button("Export collection.db…", self.choose_file, "primary")
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.selected_button.toggled.connect(self.change_mode)
        self.model.selection_changed.connect(self.update_summary)
        self.change_mode(False)

    def change_mode(self, selected):
        self.all_button.setText("All collections" if selected else "✓  All collections")
        self.selected_button.setText("✓  Choose collections" if selected else "Choose collections")
        self.model.all_collections = not selected
        self.table.setEnabled(selected)
        self.select_all_button.setEnabled(selected)
        self.clear_button.setEnabled(selected)
        self.status.setText(
            "Checked collections stay selected when searching."
            if selected
            else "All collections are included, even when searching."
        )
        self.model.changed()

    def check_all(self, checked):
        self.model.checked = {group["Id"] for group in self.model.groups} if checked else set()
        self.model.changed()

    def update_summary(self):
        identifiers = self.model.selected_ids()
        memberships = sum(
            len(group["Hashes"]) for group in self.model.groups if group["Id"] in identifiers
        )
        self.summary.setText(
            f"{len(identifiers):,} collections · {memberships:,} difficulty entries"
        )
        self.export_button.setEnabled(bool(identifiers))

    def choose_file(self):
        if not self.model.selected_ids():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export collections to collection.db",
            str(Path(self.app._directory()) / "collection.db"),
            "Collection database (*.db)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".db"
        target = Path(path).expanduser()
        if target.exists() or target.is_symlink():
            self.status.setText("That file already exists. Choose a new filename or folder.")
            return
        if not target.parent.is_dir():
            self.status.setText("Choose an existing folder for the export.")
            return
        self.destination = str(target)
        self.accept()
