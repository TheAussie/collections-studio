"""Collections Studio desktop manager with download and migration dialogs."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (  # noqa: E402
    QSettings,
    QSignalBlocker,
    QSortFilterProxyModel,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Slot,
)
from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.beatmap_downloads import Cancelled  # noqa: E402
from tools.collection_application import (  # noqa: E402
    fetch_cancellable_link,
    load_document,
    save_workspace,
)
from tools.collection_backend import Backend  # noqa: E402
from tools.collection_save import save_open_workspace  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_credits_dialog import CreditsDialog  # noqa: E402
from tools.qt_dialog_support import finish_shutdown  # noqa: E402
from tools.qt_jobs import Job  # noqa: E402
from tools.qt_models import (  # noqa: E402
    HASH_ROLE,
    IDENTITY_ROLE,
    BeatmapModel,
    CollectionModel,
    map_order,
    map_values,
)
from tools.qt_style import STYLE, button, label  # noqa: E402
from tools.stable_collections import read_replay_cache, read_stable, scan_songs  # noqa: E402

APP_TITLE = "Collections Studio"


class StudioWindow(QMainWindow):
    def __init__(self, backend=None, settings=None):
        super().__init__()
        self.backend = backend or Backend()
        self.settings = settings or QSettings("CollectionsStudio", "QtPreview")
        self.workspace = None
        self.selected = None
        self.last_import_ids = set()
        self.download_dialog = self.migration_dialog = None
        self.credits_dialog = None
        self.job = self.row_job = None
        self._closed = False
        self._writing = False
        self._view_generation = 0
        self.sort_column, self.sort_descending = -1, False
        self.pool = QThreadPool.globalInstance()
        self.collection_model = CollectionModel(self)
        self.collection_proxy = QSortFilterProxyModel(self)
        self.collection_proxy.setSourceModel(self.collection_model)
        self.collection_proxy.setFilterKeyColumn(0)
        self.collection_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.collection_proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.map_model = BeatmapModel(self)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(180)
        self.filter_timer.timeout.connect(self.filter_maps)
        self.setWindowTitle(APP_TITLE)
        self.resize(1360, 900)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(STYLE)
        self._build()
        self.map_model.sort_requested.connect(self.sort_maps)
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self._controls()
        self.show_collection()

    def _build(self):
        canvas = QWidget()
        canvas.setObjectName("canvas")
        self.setCentralWidget(canvas)
        outer = QVBoxLayout(canvas)
        outer.setContentsMargins(24, 22, 24, 16)
        outer.setSpacing(16)
        top = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(3)
        brand.addWidget(label("Collections Studio", "brand"))
        brand.addWidget(label("A place for every map."))
        top.addLayout(brand)
        top.addStretch()
        self.open_button = button("Open…", self.open_file)
        self.import_button = QToolButton()
        self.import_button.setText("Import")
        self.import_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        imports = QMenu(self)
        imports.addAction("collection.db…", self.import_file)
        imports.addAction("Maps / osu!collector link…", self.import_link)
        self.import_button.setMenu(imports)
        self.tools_button = QToolButton()
        self.tools_button.setText("Tools")
        self.tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tools = QMenu(self)
        tools.addAction("New collection.db", self.new_file)
        self.save_copy_action = tools.addAction("Save a copy…", self.save_copy)
        tools.addSeparator()
        self.library_actions = [
            tools.addAction("Read osu!.db…", self.read_database),
            tools.addAction("Scan Songs folder…", self.scan_folder),
            tools.addAction("Read Replay Parser cache…", self.read_cache),
        ]
        tools.addSeparator()
        self.download_action = tools.addAction("Get missing maps…", self.download_maps)
        self.migrate_action = tools.addAction("Migrate collections…", self.migrate_collections)
        tools.addSeparator()
        tools.addAction("Credits and licences…", self.show_credits)
        tools.addAction("About Collections Studio…", self.about)
        self.tools_button.setMenu(tools)
        self.save_button = button("Save", self.save, "primary")
        self.save_button.setToolTip(
            "Save to the opened file after creating a dated backup in the same folder."
        )
        for control in (self.open_button, self.import_button, self.tools_button, self.save_button):
            top.addWidget(control)
        outer.addLayout(top)

        workcopy = QFrame()
        workcopy.setObjectName("workcopy")
        strip = QHBoxLayout(workcopy)
        strip.setContentsMargins(14, 9, 12, 9)
        self.source_label = label("No working copy open")
        self.source_label.setMinimumWidth(0)
        self.change_label = label("Ready", "badge")
        self.undo_button = button("Undo", self.undo, "quiet")
        strip.addWidget(self.source_label, 1)
        strip.addWidget(self.change_label)
        strip.addWidget(self.undo_button)
        outer.addWidget(workcopy)

        self.splitter = QSplitter()
        sidebar = QFrame()
        sidebar.setObjectName("panel")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 16, 14, 12)
        side.setSpacing(12)
        heading = QHBoxLayout()
        self.collection_count = label("COLLECTIONS", "section")
        self.new_button = button("+ New", self.new_collection)
        heading.addWidget(self.collection_count, 1)
        heading.addWidget(self.new_button)
        side.addLayout(heading)
        self.collection_search = QLineEdit()
        self.collection_search.setPlaceholderText("Search collections")
        self.collection_search.setClearButtonEnabled(True)
        self.collection_search.setAccessibleName("Search collections")
        self.collection_search.textChanged.connect(self.filter_collections)
        side.addWidget(self.collection_search)
        self.collections = self._table(self.collection_proxy)
        self.collections.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.collections.horizontalHeader().hide()
        self.collections.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.collections.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.collections.setColumnWidth(1, 70)
        self.collections.selectionModel().currentChanged.connect(self.select_collection)
        side.addWidget(self.collections, 1)
        secondary = QHBoxLayout()
        self.rename_button = button("Rename", self.rename_collection, "quiet")
        self.delete_button = button("Delete", self.delete_collection, "danger")
        secondary.addWidget(self.rename_button)
        secondary.addStretch()
        secondary.addWidget(self.delete_button)
        side.addLayout(secondary)
        self.splitter.addWidget(sidebar)

        right = QWidget()
        content = QVBoxLayout(right)
        content.setContentsMargins(8, 0, 0, 0)
        content.setSpacing(12)
        self.heading = label("Your collection library", "heading")
        self.heading.setWordWrap(True)
        content.addWidget(self.heading)
        self.collection_summary = label("Open a collection database to get started.")
        content.addWidget(self.collection_summary)
        searches = QHBoxLayout()
        self.map_search = QLineEdit()
        self.map_search.setPlaceholderText("Search beatmaps, difficulties or MD5")
        self.map_search.setAccessibleName("Search maps")
        self.map_search.setClearButtonEnabled(True)
        self.map_search.textChanged.connect(lambda: self.filter_timer.start())
        self.status_filter = QComboBox()
        self.status_filter.addItems(
            ["All maps", "Available", "Missing", "Unresolved", "Downloaded"]
        )
        self.status_filter.setAccessibleName("Map availability filter")
        self.status_filter.currentTextChanged.connect(lambda: self.filter_timer.start())
        searches.addWidget(self.map_search, 1)
        searches.addWidget(self.status_filter)
        content.addLayout(searches)
        self.body = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.maps = self._table(self.map_model)
        self.maps.setSortingEnabled(True)
        self.maps.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.maps.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 190), (2, 75), (3, 120)):
            self.maps.setColumnWidth(column, width)
        self.maps.selectionModel().selectionChanged.connect(self.select_map)
        self.stack.addWidget(self.maps)
        empty = QFrame()
        empty.setObjectName("panel")
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(32, 24, 32, 24)
        empty_layout.addStretch()
        self.empty_heading = label("Build your collection library", "heading")
        self.empty_heading.setWordWrap(True)
        self.empty_text = label(
            "Open a stable collection.db or a copied lazer client.realm,\n"
            "or start with a new collection.db from Tools."
        )
        self.empty_text.setWordWrap(True)
        empty_layout.addWidget(self.empty_heading)
        empty_layout.addWidget(self.empty_text)
        empty_layout.addStretch()
        self.stack.addWidget(empty)
        self.body.addWidget(self.stack)
        detail_panel = QFrame()
        detail_panel.setObjectName("panel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 12, 16, 12)
        detail_layout.addWidget(label("DETAILS", "section"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Map and working copy details")
        self.details.setMinimumHeight(70)
        detail_layout.addWidget(self.details, 1)
        self.body.addWidget(detail_panel)
        self.body.setSizes([480, 145])
        self.body.setStretchFactor(0, 1)
        content.addWidget(self.body, 1)
        selection_bar = QHBoxLayout()
        self.selection_label = label("0 selected")
        self.select_all_button = button("Select all", self.maps.selectAll, "quiet")
        self.remove_button = button("Remove from collection", self.remove_maps, "danger")
        selection_bar.addWidget(self.selection_label)
        selection_bar.addStretch()
        selection_bar.addWidget(self.select_all_button)
        selection_bar.addWidget(self.remove_button)
        content.addLayout(selection_bar)
        self.splitter.addWidget(right)
        self.splitter.setSizes([280, 1000])
        self.splitter.setStretchFactor(1, 1)
        outer.addWidget(self.splitter, 1)
        footer = QHBoxLayout()
        self.status = label("All edits stay in the working copy until you save a new file.")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(100)
        self.progress.hide()
        self.cancel_button = button("Cancel", self.cancel_job, "quiet")
        self.cancel_button.hide()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.progress)
        footer.addWidget(self.cancel_button)
        outer.addLayout(footer)
        for shortcut, callback in (
            ("Ctrl+O", self.open_file),
            ("Ctrl+S", self.save),
            ("Ctrl+Z", self.undo),
            ("F2", self.rename_collection),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def _table(self, model):
        table = QTableView()
        table.setModel(model)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(max(44, table.fontMetrics().height() + 22))
        table.setWordWrap(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return table

    def _controls(self):
        blocked = (
            self.job is not None
            or self.download_dialog is not None
            or self.migration_dialog is not None
        )
        loaded = self.workspace is not None and not blocked
        selected = loaded and self.selected is not None
        for widget in (self.import_button, self.new_button):
            widget.setEnabled(loaded)
        for widget in (self.rename_button, self.delete_button):
            widget.setEnabled(selected)
        self.open_button.setEnabled(not blocked)
        self.tools_button.setEnabled(not blocked)
        self.collections.setEnabled(not blocked)
        self.download_action.setEnabled(loaded)
        self.migrate_action.setEnabled(loaded and bool(self.workspace.collections))
        self.save_button.setEnabled(
            loaded and (self.workspace.dirty or not self.workspace.source_path)
        )
        self.save_copy_action.setEnabled(loaded)
        self.undo_button.setEnabled(loaded and self.workspace.can_undo)
        self.select_all_button.setEnabled(selected and self.map_model.rowCount() > 0)
        self.remove_button.setEnabled(selected and bool(self.maps.selectionModel().selectedRows()))
        for action in self.library_actions:
            action.setEnabled(loaded and self.workspace.format == "stable")
        if self.workspace:
            dirty = self.workspace.dirty
            self.change_label.setText(
                "Unsaved changes"
                if dirty
                else "New file"
                if not self.workspace.source_path
                else "Unchanged"
            )
            filename = (
                Path(self.workspace.source_path).name
                if self.workspace.source_path
                else "New collection.db"
            )
            self.source_label.setText(f"Working copy · {self.workspace.format} · {filename}")
            self.source_label.setToolTip(self.workspace.source_path or "Not saved yet")
            self.setWindowTitle(("● " if dirty else "") + APP_TITLE)
        self.collection_count.setText(f"COLLECTIONS  {len(self.collection_model.groups)}")

    def refresh_collections(self):
        wanted = self.selected
        blocker = QSignalBlocker(self.collections.selectionModel())
        self.collection_model.replace(self.workspace.collections if self.workspace else [])
        self.collection_proxy.sort(0)
        self.selected = None
        for row in range(self.collection_proxy.rowCount()):
            index = self.collection_proxy.index(row, 0)
            if row == 0 or index.data(IDENTITY_ROLE) == wanted:
                self.collections.setCurrentIndex(index)
                self.selected = index.data(IDENTITY_ROLE)
            if self.selected == wanted:
                break
        del blocker
        self.show_collection()
        self._controls()

    def filter_collections(self, text):
        self.collection_proxy.setFilterFixedString(text)
        index = self.collections.currentIndex()
        if not index.isValid() and self.collection_proxy.rowCount():
            self.collections.setCurrentIndex(self.collection_proxy.index(0, 0))
        else:
            self.select_collection(index)

    def select_collection(self, current, _previous=None):
        self.selected = current.data(IDENTITY_ROLE) if current.isValid() else None
        self.show_collection()
        self._controls()

    def show_collection(self):
        self._view_generation += 1
        self.filter_timer.stop()
        if self.row_job:
            self.row_job.stop.set()
            self.row_job = None
        group = (
            self.workspace.collection(self.selected) if self.workspace and self.selected else None
        )
        self.map_model.replace(
            group["Hashes"] if group else [],
            self.workspace.beatmaps if self.workspace else {},
            self.workspace.present_hashes if self.workspace else set(),
            downloaded=self.workspace.downloaded if self.workspace else {},
        )
        self.heading.setText(group["Name"] if group else "Your collection library")
        self.collection_summary.setText(
            f"{len(group['Hashes']):,} maps · Exact difficulty memberships"
            if group
            else "Open a database or create a new collection.db from Tools."
        )
        self.stack.setCurrentIndex(0 if group and group["Hashes"] else 1)
        self.empty_heading.setText(
            "This collection is empty" if group else "Build your collection library"
        )
        self.empty_text.setText(
            "Import a collection.db or a collection link to add memberships."
            if group
            else "Open a stable collection.db or a copied lazer client.realm,\n"
            "or start with a new collection.db from Tools."
        )
        self.select_map()
        if group and (
            self.map_search.text() or self.status_filter.currentIndex() or self.sort_column >= 0
        ):
            self.filter_timer.start()

    def sort_maps(self, column, order):
        self.sort_column = column
        self.sort_descending = order == Qt.SortOrder.DescendingOrder
        self.filter_timer.start()

    def filter_maps(self):
        if self._closed or not self.workspace or not self.selected:
            return
        if self.row_job:
            self.row_job.stop.set()
        hashes = self.map_model.hashes
        metadata, present = self.workspace.beatmaps, self.workspace.present_hashes
        downloaded = dict(self.workspace.downloaded)
        query, status = self.map_search.text(), self.status_filter.currentText()
        column, descending = self.sort_column, self.sort_descending
        self.row_job = Job(
            lambda stop, _progress: map_order(
                hashes, metadata, present, query, status, column, descending, stop, downloaded
            )
        )
        self._row_context = (self.workspace, self.selected, self._view_generation)
        self.row_job.signals.finished.connect(self._rows_finished)
        self.collection_summary.setText(f"Searching {len(hashes):,} maps…")
        self.pool.start(self.row_job)

    @Slot(object)
    def _rows_finished(self, outcome):
        token, order, error = outcome
        if self._closed or not self.row_job or token != self.row_job.token:
            return
        self.row_job = None
        if self._row_context != (self.workspace, self.selected, self._view_generation) or error:
            return
        self.map_model.reorder(order)
        self.collection_summary.setText(
            f"{len(order):,} of {len(self.map_model.hashes):,} maps · Exact difficulty memberships"
        )
        self.stack.setCurrentIndex(0 if order else 1)
        if not order:
            self.empty_heading.setText("No matching maps")
            self.empty_text.setText("Try a different search or availability filter.")
        self.select_map()
        self._controls()

    def selected_hashes(self):
        return [index.data(HASH_ROLE) for index in self.maps.selectionModel().selectedRows()]

    def select_map(self, *_args):
        hashes = self.selected_hashes()
        self.selection_label.setText(f"{len(hashes):,} selected")
        source = self.workspace.source_path if self.workspace else "No file open"
        if len(hashes) == 1:
            checksum = hashes[0]
            meta = self.workspace.beatmaps.get(checksum.lower(), {})
            values = map_values(
                checksum,
                self.workspace.beatmaps,
                self.workspace.present_hashes,
                self.workspace.downloaded,
            )
            text = (
                f"{values[0]}\nDifficulty: {values[1]}  ·  {values[2]}  ·  {values[3]}\n"
                f"MD5: {checksum}"
            )
            if meta.get("BeatmapId"):
                text += f"\nBeatmap ID: {meta['BeatmapId']}"
            if meta.get("SetId"):
                text += f"  ·  Beatmapset ID: {meta['SetId']}"
            if values[3] == "Unresolved":
                text += "\nOnly the original MD5 is known. Its membership is preserved."
            if values[3] == "Downloaded":
                text += "\nVerified archive: " + self.workspace.downloaded[checksum.lower()]
                text += "\nImport this archive into osu! and refresh the inventory "
                text += "to mark it available."
            text += "\nWorking from: " + source
        else:
            text = (
                (
                    f"{len(hashes):,} selected memberships.\n"
                    if hashes
                    else "Select a map for its difficulty, status and exact MD5.\n"
                )
                + "Working from: "
                + source
                + "\nEdits stay in memory. Saving creates a separate verified file."
            )
        self.details.setPlainText(text)
        self._controls()

    def _discard_ok(self):
        return (
            not self.workspace
            or not self.workspace.dirty
            or QMessageBox.question(
                self,
                "Discard unsaved changes?",
                "Discard changes in this working copy?",
                defaultButton=QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def new_file(self):
        if self.job or self.download_dialog or self.migration_dialog or not self._discard_ok():
            return
        self.workspace = Workspace(
            {"Format": "stable", "Version": 20261026, "SourceRealmSha256": "", "Collections": []},
            "",
        )
        self.selected = None
        self.last_import_ids.clear()
        self.collection_search.clear()
        self.refresh_collections()
        self.status.setText("New collection.db. Create a collection or import memberships.")

    def open_file(self):
        if self.job or self.download_dialog or self.migration_dialog or not self._discard_ok():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open collection.db or client.realm",
            self._directory(),
            "Collection databases (*.db *.realm);;All files (*)",
        )
        if path:
            self.load_path(path)

    def load_path(self, path):
        if self.job or self.download_dialog or self.migration_dialog:
            return
        if (
            str(path).lower().endswith(".realm")
            and QMessageBox.question(
                self,
                "Open client.realm",
                "Close osu!lazer before opening or saving this database. "
                "Save creates a dated backup, then updates this file in its current folder.\n\n"
                "Is osu!lazer closed?",
                defaultButton=QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._remember_directory(path)

        def loaded(document):
            self.workspace = Workspace(document, str(Path(path).resolve()))
            self.selected = None
            self.last_import_ids.clear()
            self.collection_search.clear()
            self.refresh_collections()
            self.status.setText(
                f"Loaded {len(self.workspace.collections):,} collections. Source file unchanged."
                + (
                    " Inventory: " + document["LibraryError"]
                    if document.get("LibraryError")
                    else ""
                )
            )

        self._task(
            "Reading collections and library metadata…",
            lambda _stop, _progress: load_document(path, self.backend),
            loaded,
        )

    def _edit(self, operation):
        if self.job or self.download_dialog or self.migration_dialog or not self.workspace:
            return
        try:
            operation()
            self.refresh_collections()
            created, edited, deleted = self.workspace.summary()
            self.status.setText(
                f"Working copy: {created} new, {edited} edited, {deleted} deleted collections. "
                "Undo is available."
            )
        except ValueError as error:
            self.error(error)

    def new_collection(self):
        if not self.workspace or self.job:
            return
        name, accepted = QInputDialog.getText(self, "New collection", "Collection name")
        if accepted:

            def create():
                self.collection_search.clear()
                self.selected = self.workspace.create(name)

            self._edit(create)

    def rename_collection(self):
        if not self.selected or self.job:
            return
        group = self.workspace.collection(self.selected)
        name, accepted = QInputDialog.getText(
            self, "Rename collection", "Collection name", text=group["Name"]
        )
        if accepted:
            self._edit(lambda: self.workspace.rename(self.selected, name))

    def delete_collection(self):
        if self.selected and not self.job:
            group = self.workspace.collection(self.selected)
            if (
                QMessageBox.question(
                    self,
                    "Delete collection?",
                    f"Delete “{group['Name']}” from this working copy?\n"
                    "Beatmap files stay saved. You can undo this change.",
                    defaultButton=QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            ):
                self._edit(lambda: self.workspace.delete(self.selected))

    def remove_maps(self):
        if self.selected and not self.job:
            hashes = self.selected_hashes()
            if hashes:
                self._edit(lambda: self.workspace.remove_maps(self.selected, hashes))

    def undo(self):
        if self.workspace and not self.job:
            self.workspace.undo()
            self.refresh_collections()
            self.status.setText("Last collection edit undone.")

    def import_file(self):
        if not self.workspace or self.job:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import collection.db",
            self._directory(),
            "Stable collection database (*.db);;All files (*)",
        )
        if path:
            self._task(
                "Reading collection.db…", lambda _stop, _progress: read_stable(path), self._imported
            )

    def import_link(self):
        if not self.workspace or self.job:
            return
        value, accepted = QInputDialog.getText(
            self,
            "Import collection link",
            "Maps import link, osu!collector collection URL, or osu!collector ID",
        )
        if accepted and value:
            self._task(
                "Fetching collection contents…",
                lambda stop, _progress: fetch_cancellable_link(value, stop),
                self._imported,
            )

    def _imported(self, document):
        created, added = self.workspace.merge(document["Collections"])
        for checksum, details in document.get("Beatmaps", {}).items():
            self.workspace.beatmaps.setdefault(checksum, details)
        names = {group["Name"] for group in document["Collections"]}
        self.last_import_ids = {
            group["Id"] for group in self.workspace.collections if group["Name"] in names
        }
        self.collection_search.clear()
        self.selected = next(
            (group["Id"] for group in self.workspace.collections if group["Name"] in names),
            self.selected,
        )
        self.refresh_collections()
        self.status.setText(
            f"Imported {created} new collections and {added:,} memberships. "
            + " ".join(document.get("Warnings", []))
        )

    def read_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Read osu!.db — read only", self._directory(), "osu! database (*.db)"
        )
        if path:
            from tools.osu_database import read_osu_database

            self._task(
                "Reading installed beatmap hashes…",
                lambda _stop, _progress: read_osu_database(path),
                self._library_loaded,
            )

    def read_cache(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Read Replay Parser cache", self._directory(), "Beatmap index (*.json)"
        )
        if path:
            self._task(
                "Checking cached beatmap paths…",
                lambda _stop, _progress: read_replay_cache(path),
                self._library_loaded,
            )

    def scan_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Scan Songs folder — read only", self._directory()
        )
        if folder:
            cache = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
            self._task(
                "Scanning Songs…",
                lambda stop, progress: scan_songs(
                    folder, stop=stop, progress=progress, cache_directory=cache
                ),
                self._library_loaded,
            )

    def _library_loaded(self, document):
        self.workspace.beatmaps.update(document["Beatmaps"])
        self.workspace.present_hashes = self.workspace.database_hashes | set(document["Beatmaps"])
        self.show_collection()
        self.status.setText(
            f"Loaded {document['Scanned']:,} beatmaps; "
            f"{document['ErrorCount']} stale/unreadable entries. Collection memberships unchanged."
        )

    def save(self):
        if (
            self.job
            or self.download_dialog
            or self.migration_dialog
            or not self.workspace
            or (not self.workspace.dirty and self.workspace.source_path)
        ):
            return
        new_path = None
        if not self.workspace.source_path:
            new_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save new collection.db",
                str(Path(self._directory()) / "collection.db"),
                "Collection database (*.db)",
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
            if not new_path:
                return
            if not Path(new_path).suffix:
                new_path += ".db"
        workspace = self.workspace

        def saved(report):
            workspace.mark_saved(report["OutputFile"], report["OutputSha256"])
            self._remember_directory(report["OutputFile"])
            self.refresh_collections()
            self.status.setText(
                (
                    "Saved. Previous database backed up as " + Path(report["BackupFile"]).name + "."
                    if report["BackupFile"]
                    else "Saved the new collection.db."
                )
                + " ".join(report.get("Warnings", []))
            )
            self.details.setPlainText(
                "Saved: "
                + report["OutputFile"]
                + ("\nBackup: " + report["BackupFile"] if report["BackupFile"] else "")
                + "\nVerification report: "
                + report["ReportPath"]
            )

        self._task(
            "Verifying changes, creating a backup and saving…",
            lambda _stop, _progress: save_open_workspace(
                workspace, self.backend, new_path=new_path
            ),
            saved,
            writing=True,
        )

    def save_copy(self):
        if self.job or self.download_dialog or self.migration_dialog or not self.workspace:
            return
        parent = QFileDialog.getExistingDirectory(
            self, "Choose parent folder for a NEW verified collections copy", self._directory()
        )
        if not parent:
            return
        output = Path(parent) / (
            "collections-export-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
        )
        filename = "collection.db" if self.workspace.format == "stable" else "client.realm"
        created, edited, deleted = self.workspace.summary()
        if (
            QMessageBox.question(
                self,
                "Save new collections copy?",
                f"Create {created}, edit {edited}, delete {deleted} collections in a NEW file?\n\n"
                f"{output / filename}\n\n"
                "The source remains as your backup. No existing file is replaced.",
                defaultButton=QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        workspace = self.workspace

        def saved(report):
            stable = workspace.format == "stable"
            path = report["OutputFile"] if stable else report["OutputRealm"]
            checksum = report["OutputSha256"] if stable else report["OutputRealmSha256"]
            workspace.mark_saved(path, checksum)
            self.refresh_collections()
            self.status.setText(
                "Saved and reopened the new copy successfully. Original source preserved."
            )
            self.details.setPlainText(
                "Saved: " + path + "\nVerification report: " + str(output / "import-report.json")
            )

        self._task(
            "Saving and verifying a new collections copy…",
            lambda _stop, _progress: save_workspace(workspace, output, self.backend),
            saved,
            writing=True,
        )

    def _task(self, message, work, done, writing=False):
        if self.job or self._closed or self.download_dialog or self.migration_dialog:
            return
        self.job = Job(work)
        self._job_workspace = self.workspace
        self._job_done = done
        self._writing = writing
        self.job.signals.finished.connect(self._finished)
        self.job.signals.progress.connect(self._progress)
        self.status.setText(message)
        self.progress.show()
        self.cancel_button.setVisible(not writing)
        self.cancel_button.setEnabled(True)
        self._controls()
        self.pool.start(self.job)

    @Slot(str, str)
    def _progress(self, token, text):
        if not self._closed and self.job and self.job.token == token:
            self.status.setText(text)

    @Slot(object)
    def _finished(self, outcome):
        token, result, error = outcome
        if self._closed or not self.job or token != self.job.token:
            return
        cancelled = self.job.stop.is_set() or isinstance(error, Cancelled)
        self.job = None
        self._writing = False
        self.progress.hide()
        self.cancel_button.hide()
        if cancelled:
            self.status.setText("Cancelled. Working copy unchanged by this operation.")
        elif self.workspace is self._job_workspace:
            if error:
                self.error(error)
            else:
                try:
                    self._job_done(result)
                except Exception as caught:
                    self.error(caught)
        self._controls()

    def cancel_job(self):
        if self.job and not self._writing:
            self.job.stop.set()
            self.cancel_button.setEnabled(False)
            self.status.setText(
                "Cancelling… The current file read or network request may need to finish."
            )

    def error(self, error):
        message = str(error)
        if isinstance(error, PermissionError):
            message += "\n\nClose osu! and check that the database and its folder are writable."
        self.status.setText("The operation did not complete. Review the error before retrying.")
        logging.getLogger("collections-studio").error("Operation failed: %s", type(error).__name__)
        QMessageBox.critical(self, "Collections Studio", message)

    def _directory(self):
        return self.settings.value(
            "directory",
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation),
        )

    def _remember_directory(self, path):
        self.settings.setValue("directory", str(Path(path).resolve().parent))

    def show_credits(self):
        try:
            if self.credits_dialog is None:
                self.credits_dialog = CreditsDialog(self)
            self.credits_dialog.show()
            self.credits_dialog.raise_()
            self.credits_dialog.activateWindow()
        except RuntimeError as error:
            self.error(str(error))

    def about(self):
        QMessageBox.information(
            self,
            APP_TITLE,
            "osu! collection manager.\n\n"
            "Open, edit, undo, import, inspect inventory and save changes with automatic backups. "
            "Tools → Save a copy keeps separate exports available. "
            "Tools includes verified downloads with saved-queue resume "
            "and collection migration.\n\n"
            "MIT licence — © 2026 TheAussie and Collections Studio contributors. "
            "Use Tools → Credits and licences for acknowledgements and licence texts.\n\n"
            "Manual clean-Windows acceptance remains pending.",
        )

    def closeEvent(self, event):
        for dialog in (self.download_dialog, self.migration_dialog):
            if dialog is not None and not dialog._closed:
                dialog.close()
                event.ignore()
                return
        if self.job and self._writing:
            self.status.setText("Wait for saving and verification to finish before closing.")
            event.ignore()
            return
        if not self._discard_ok():
            event.ignore()
            return
        self._closed = True
        if self.job:
            self.job.stop.set()
        if self.row_job:
            self.row_job.stop.set()
        self.filter_timer.stop()
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()

    def download_maps(self):
        if self.job or not self.workspace or self.migration_dialog:
            return
        if self.download_dialog:
            self.download_dialog.raise_()
            return
        from tools.qt_download_dialog import DownloadDialog

        self._open_dialog("download_dialog", DownloadDialog(self))

    def migrate_collections(self):
        if self.job or not self.workspace or not self.workspace.collections or self.download_dialog:
            return
        if self.migration_dialog:
            self.migration_dialog.raise_()
            return
        from tools.qt_migration_dialog import MigrationDialog

        self._open_dialog("migration_dialog", MigrationDialog(self))

    def _open_dialog(self, name, dialog):
        self.filter_timer.stop()
        if self.row_job:
            self.row_job.stop.set()
            self.row_job = None
        setattr(self, name, dialog)
        dialog.finished.connect(lambda _result: self._dialog_finished(name, dialog))
        self._controls()
        dialog.show()

    def _dialog_finished(self, name, dialog):
        if getattr(self, name) is dialog:
            setattr(self, name, None)
        if not self._closed:
            if self.workspace is dialog.workspace:
                self.refresh_collections()
            self._controls()


def configure_appearance(app):
    app.setStyle("Fusion")
    font = app.font()
    font.setPointSizeF(max(10.0, font.pointSizeF()))
    app.setFont(font)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="Open a stable collection.db or copied client.realm")
    parser.add_argument("--self-test", action="store_true", help="Run disposable packaged checks")
    parser.add_argument("--report", type=Path, help="Write packaged self-test results here")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("CollectionsStudio")
    app.setApplicationName("CollectionsStudioQt")
    app.setApplicationDisplayName(APP_TITLE)
    configure_appearance(app)
    if args.self_test:
        from tools.qt_package_smoke import run_smoke

        if not args.report:
            parser.error("--self-test requires --report FILE")
        run_smoke(args.report)
        return 0
    log_folder = (
        Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        / "logs"
    )
    log_folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_folder / "studio.log", encoding="utf-8", level=logging.INFO)
    logging.getLogger("collections-studio").info("Collections Studio started on %s", sys.platform)
    window = StudioWindow()
    window.show()
    if args.file:
        QTimer.singleShot(0, lambda: window.load_path(args.file))
    result = app.exec()
    finish_shutdown(window)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
