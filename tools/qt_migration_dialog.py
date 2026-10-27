"""Qt collection migration dialog; the existing snapshot/verification engine owns writes."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSortFilterProxyModel, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from tools.collection_migration import capture_source, migrate
from tools.qt_dialog_support import StudioDialog
from tools.qt_jobs import Job
from tools.qt_models import IDENTITY_ROLE, CollectionModel
from tools.qt_style import button, label


class MigrationDialog(StudioDialog):
    def __init__(self, app, migrate_function=migrate):
        super().__init__(app, "Migrate collections")
        self.resize(1000, 800)
        self.setMinimumSize(900, 700)
        self.to_stable = self.workspace.format == "realm"
        self.migrate_function = migrate_function
        self.job = None
        self.result = None
        self.current_id = app.selected
        self.output_name = self.new_output_name()
        self.model = CollectionModel(self)
        self.model.replace(self.workspace.collections)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.sort(0)
        self._build()
        self.table.selectAll()
        self.controls()

    @staticmethod
    def new_output_name():
        return (
            "collections-migration-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
        )

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        direction = "lazer → stable" if self.to_stable else "stable → lazer"
        layout.addWidget(label("Migrate collections · " + direction, "heading"))
        layout.addWidget(label("Copy all or selected collections into a verified new file."))
        if self.workspace.dirty:
            layout.addWidget(label("Includes your unsaved collection edits", "badge"))
        selection = QHBoxLayout()
        self.all_button = button("Select all", self.select_all)
        self.clear_button = button("Clear selection", lambda: self.table.clearSelection(), "quiet")
        self.current_button = button("Current collection", self.select_current, "quiet")
        self.selection_label = label()
        for control in (self.all_button, self.clear_button, self.current_button):
            selection.addWidget(control)
        selection.addStretch()
        selection.addWidget(self.selection_label)
        layout.addLayout(selection)
        self.table = self.app._table(self.proxy)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 100)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.merge_existing = QCheckBox("Merge with an existing collection.db", self)
        self.merge_existing.setChecked(not self.to_stable)
        if self.to_stable:
            layout.addWidget(self.merge_existing)
        else:
            self.merge_existing.hide()
            layout.addWidget(
                label("Destination · choose an existing copied client.realm", "section")
            )
        self.merge_existing.toggled.connect(self.controls)
        target_row = QHBoxLayout()
        self.target = QLineEdit()
        self.target.setAccessibleName("Destination database copy")
        self.target.setPlaceholderText(
            "Existing collection.db" if self.to_stable else "Copied client.realm"
        )
        self.target_button = button("Browse…", self.choose_target)
        target_row.addWidget(self.target, 1)
        target_row.addWidget(self.target_button)
        layout.addLayout(target_row)
        self.realm_closed = QCheckBox("osu!lazer is closed and this is a separate Realm copy", self)
        self.realm_closed.setVisible(not self.to_stable)
        layout.addWidget(self.realm_closed)
        layout.addWidget(
            label("Matching names merge by MD5. Other destination collections stay present.")
        )
        layout.addWidget(label("Create the result inside this folder", "section"))
        output = QHBoxLayout()
        parent = (
            str(Path(self.workspace.source_path).resolve().parent)
            if self.workspace.source_path
            else self.app._directory()
        )
        self.output_parent = QLineEdit(parent)
        self.output_parent.setAccessibleName("Migration output parent folder")
        self.parent_button = button("Browse…", self.choose_parent)
        self.output_parent.textChanged.connect(self.update_output)
        output.addWidget(self.output_parent, 1)
        output.addWidget(self.parent_button)
        layout.addLayout(output)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(65)
        self.details.setMaximumHeight(110)
        self.details.setAccessibleName("Migration output and verification report")
        layout.addWidget(self.details)
        self.update_output()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.start_button = button(
            "Migrate to " + ("collection.db" if self.to_stable else "client.realm"),
            self.start,
            "primary",
        )
        self.open_button = button("Open output folder", self.open_result, "quiet")
        self.close_button = button("Close", self.close, "quiet")
        actions.addWidget(self.start_button)
        actions.addWidget(self.open_button)
        actions.addStretch()
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.status = label("Your input files and editing session stay unchanged.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def selected_ids(self):
        return [index.data(IDENTITY_ROLE) for index in self.table.selectionModel().selectedRows()]

    def selection_changed(self, *_args):
        ids = set(self.selected_ids())
        count = sum(
            len(group["Hashes"]) for group in self.workspace.collections if group["Id"] in ids
        )
        self.selection_label.setText(f"{len(ids):,} collections · {count:,} memberships")
        if hasattr(self, "start_button"):
            self.controls()

    def select_all(self):
        self.table.selectAll()

    def select_current(self):
        self.table.clearSelection()
        for row in range(self.proxy.rowCount()):
            if self.proxy.index(row, 0).data(IDENTITY_ROLE) == self.current_id:
                self.table.selectRow(row)
                break

    def controls(self):
        idle = self.job is None
        for widget in (
            self.table,
            self.all_button,
            self.clear_button,
            self.current_button,
            self.output_parent,
            self.parent_button,
            self.merge_existing,
            self.realm_closed,
        ):
            widget.setEnabled(idle)
        target_enabled = idle and self.merge_existing.isChecked()
        self.target.setEnabled(target_enabled)
        self.target_button.setEnabled(target_enabled)
        self.start_button.setEnabled(idle and bool(self.selected_ids()))
        self.open_button.setEnabled(idle and self.result is not None)
        self.close_button.setEnabled(idle)

    def choose_target(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose destination database copy",
            self.app._directory(),
            "Collection database (*.db)" if self.to_stable else "Realm copy (*.realm)",
        )
        if path:
            self.target.setText(path)
            self.realm_closed.setChecked(False)

    def choose_parent(self):
        path = QFileDialog.getExistingDirectory(
            self, "Create migrated collections here", self.output_parent.text()
        )
        if path:
            self.output_parent.setText(path)

    def update_output(self):
        if hasattr(self, "details"):
            filename = "collection.db" if self.to_stable else "client.realm"
            self.details.setPlainText(
                "New file: "
                + str(Path(self.output_parent.text()).expanduser() / self.output_name / filename)
                + "\nNo existing file will be replaced."
            )

    def start(self):
        if self.job or self._closed:
            return
        try:
            source = capture_source(self.workspace, self.selected_ids())
            target = self.target.text().strip() if self.merge_existing.isChecked() else ""
            if self.merge_existing.isChecked() and (
                not target or not Path(target).expanduser().is_file()
            ):
                raise ValueError("Choose the destination database copy first.")
            if not self.to_stable and not self.realm_closed.isChecked():
                raise ValueError(
                    "Confirm that lazer is closed and the destination is a separate Realm copy."
                )
            parent = Path(self.output_parent.text()).expanduser()
            if not self.output_parent.text() or not parent.is_dir():
                raise ValueError("Choose an existing output parent folder.")
            output = parent / self.output_name
            if output.exists() or output.is_symlink():
                raise ValueError("Output already exists. Choose a new output folder.")
        except ValueError as error:
            self.status.setText(str(error))
            return
        filename = "collection.db" if self.to_stable else "client.realm"
        count = sum(len(group["Hashes"]) for group in source["Collections"])
        if (
            QMessageBox.question(
                self,
                "Create a new migrated copy?",
                f"Copy {len(source['Collections']):,} collections and {count:,} memberships?\n\n"
                f"{output / filename}\n\n"
                + ("Includes staged, unsaved collection edits.\n" if source["UnsavedEdits"] else "")
                + "Inputs stay unchanged. Matching collection names merge by MD5.",
                defaultButton=QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        backend, migrate_function = self.app.backend, self.migrate_function
        self.job = Job(
            lambda _stop, _progress: migrate_function(
                source, output, backend=backend, target_path=target
            )
        )
        self.job.signals.finished.connect(self.finished_migration)
        self.progress.setRange(0, 0)
        self.status.setText(
            "Creating and verifying a new copy… Wait for verification before closing."
        )
        self.controls()
        self.app.pool.start(self.job)

    @Slot(object)
    def finished_migration(self, outcome):
        token, result, error = outcome
        if self._closed or not self.job or token != self.job.token:
            return
        self.job = None
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if error is None else 0)
        if error:
            self.status.setText("Migration did not complete. Review the error before retrying.")
            self.details.setPlainText(str(error))
            self.error(error)
        else:
            self.result = result
            self.status.setText(
                f"Verified · {result['Created']:,} new collections · "
                f"{result['Updated']:,} merged · "
                f"{result['AddedMemberships']:,} added memberships"
            )
            self.output_name = self.new_output_name()
            self.details.setPlainText(
                "Saved: "
                + result["OutputFile"]
                + "\nReport: "
                + result["ReportPath"]
                + "\nYour input files and editing session are unchanged."
            )
        self.controls()

    def open_result(self):
        if self.result:
            self.open_folder(Path(self.result["OutputFile"]).parent)

    def can_close(self):
        if self.job:
            self.status.setText("Wait for copying and verification to finish before closing.")
            return False
        return True
