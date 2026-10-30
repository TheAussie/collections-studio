"""Qt download queue using the existing exact-MD5 engine and persistent queue format."""

import queue
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from tools.beatmap_downloads import (
    MIRRORS,
    Cancelled,
    Downloader,
    download_counts,
    load_download_progress,
)
from tools.qt_dialog_support import StudioDialog
from tools.qt_jobs import Job
from tools.qt_models import HASH_ROLE, ROOT_INDEX
from tools.qt_style import button, label

SAVED_SCOPE = "Saved download queue"


class DownloadModel(QAbstractTableModel):
    def __init__(self, metadata, parent=None):
        super().__init__(parent)
        self.metadata = dict(metadata)
        self.hashes, self.positions, self.states = [], {}, {}

    def replace(self, hashes):
        self.beginResetModel()
        self.hashes = list(hashes)
        self.positions = {checksum: row for row, checksum in enumerate(self.hashes)}
        self.endResetModel()

    def rowCount(self, parent=ROOT_INDEX):
        return 0 if parent.isValid() else len(self.hashes)

    def columnCount(self, parent=ROOT_INDEX):
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("BEATMAP", "DIFFICULTY", "STATUS", "MIRROR")[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.hashes):
            return None
        checksum = self.hashes[index.row()]
        if role == HASH_ROLE:
            return checksum
        meta, state = self.metadata.get(checksum, {}), self.states.get(checksum, {})
        title = meta.get("Title") or "Waiting for MD5 lookup"
        if meta.get("Artist"):
            title = meta["Artist"] + " — " + title
        status = state.get("state", "Queued")
        values = (
            title,
            meta.get("Difficulty") or "—",
            (
                "Already installed"
                if state.get("installed")
                else "Already downloaded"
                if state.get("reused")
                else "Ready for import"
            )
            if status == "Ready"
            else status,
            state.get("mirror", "—"),
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(
                [title, values[1], checksum, state.get("message", state.get("file", status))]
            )
        return None

    def changed(self, checksum):
        row = self.positions.get(checksum)
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, 3))


class DownloadDialog(StudioDialog):
    def __init__(self, app, downloader=None, mirrors=MIRRORS):
        super().__init__(app, "Missing beatmaps")
        self.resize(1100, 800)
        self.setMinimumSize(920, 700)
        self.downloader = downloader or Downloader()
        self.mirrors = mirrors
        self.job = None
        self.phase = None
        self.terminal = None
        self.close_requested = False
        self.events = queue.Queue(maxsize=512)
        self.saved_hashes = []
        self.resume_mode = False
        self.report_path = None
        self.model = DownloadModel(self.workspace.beatmaps, self)
        self._build()
        self.scan()
        self.pump_timer = QTimer(self)
        self.pump_timer.setInterval(40)
        self.pump_timer.timeout.connect(self.pump)
        self.pump_timer.start()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label("Get missing beatmaps", "heading"))
        layout.addWidget(
            label("Save verified .osz archives, then import them into your osu! client.")
        )
        scope_row = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        if self.app.last_import_ids:
            self.scope.addItem("Last import")
        self.scope.addItems(["Selected collection", "All collections"])
        if not self.app.selected:
            self.scope.setCurrentText("All collections")
        self.scope.setAccessibleName("Collections to check for missing maps")
        self.scope.currentTextChanged.connect(self.scan)
        self.count = label()
        self.count.setWordWrap(True)
        scope_row.addWidget(label("Check"))
        scope_row.addWidget(self.scope)
        scope_row.addWidget(self.count, 1)
        layout.addLayout(scope_row)
        layout.addWidget(label("Mirror order · left to right, top to bottom"))
        mirror_grid = QGridLayout()
        self.mirror_flags = {}
        for index, mirror in enumerate(self.mirrors):
            check = QCheckBox(mirror.name)
            check.setChecked(True)
            self.mirror_flags[mirror.name] = check
            mirror_grid.addWidget(check, index // 4, index % 4)
        layout.addLayout(mirror_grid)
        layout.addWidget(
            label("MD5 lookup: " + ", ".join(m.name for m in self.mirrors if m.lookup))
        )
        self.official_api = QCheckBox("Use my osu! API credentials after mirror lookup fails")
        self.official_api.setChecked(
            self.app.settings.value("downloads/use-official-api", False, type=bool)
        )
        layout.addWidget(self.official_api)
        layout.addWidget(button("osu! API credentials…", self.app.show_osu_credentials))
        destination = QHBoxLayout()
        self.directory = QLineEdit(self.app.settings.value("downloads/directory", ""))
        self.directory.setPlaceholderText("Choose the folder for archives and the saved queue")
        self.directory.setAccessibleName("Download folder")
        self.directory.textEdited.connect(self.reset_states)
        self.browse_button = button("Browse…", self.choose_folder)
        self.resume_button = button("Resume queue…", self.resume_queue)
        destination.addWidget(self.directory, 1)
        destination.addWidget(self.browse_button)
        destination.addWidget(self.resume_button)
        layout.addLayout(destination)
        self.table = self.app._table(self.model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 180), (2, 190), (3, 120)):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(65)
        self.details.setMaximumHeight(100)
        self.details.setAccessibleName("Download details and exact MD5")
        self.details.setPlainText("Select a map for its original MD5 and download result.")
        layout.addWidget(self.details)
        controls = QHBoxLayout()
        self.start_button = button("Download missing", self.start, "primary")
        self.selected_button = button("Download selected", lambda: self.start(selected=True))
        self.retry_button = button("Retry failed", lambda: self.start(retry=True))
        self.select_all_button = button("Select all", self.table.selectAll, "quiet")
        self.cancel_button = button("Cancel", self.cancel, "quiet")
        self.close_button = button("Close", self.close, "quiet")
        for control in (
            self.start_button,
            self.selected_button,
            self.retry_button,
            self.select_all_button,
        ):
            controls.addWidget(control)
        controls.addStretch()
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.status = label("Choose a folder, or resume a previously saved queue.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def reset_states(self):
        if not self.job:
            self.model.states.clear()
            self.model.replace(self.model.hashes)
            self.progress.setValue(0)
            self.controls()

    def scan(self):
        if self.job:
            return
        scope = self.scope.currentText()
        if scope == SAVED_SCOPE:
            hashes = [h for h in self.saved_hashes if h not in self.workspace.present_hashes]
        else:
            ids = (
                self.app.last_import_ids
                if scope == "Last import"
                else {self.app.selected}
                if scope == "Selected collection"
                else None
            )
            hashes = self.workspace.missing_hashes(ids)
            self.resume_mode = False
        self.model.replace(hashes)
        self.count.setText(f"{len(hashes):,} unique hashes missing from this library")
        self.controls()

    def controls(self):
        idle = self.job is None
        ready, pending, failed, installed = download_counts(self.model.hashes, self.model.states)
        self.count.setText(
            "Queue check cancelled; resume to restore counts."
            if self.phase == "unchecked"
            else "Checking saved queue…"
            if not idle and self.phase == "download" and not self.prepared
            else f"{ready - installed:,} downloaded · {installed:,} installed · "
            f"{pending:,} remaining · {failed:,} failed"
        )
        for widget in (
            self.scope,
            self.directory,
            self.browse_button,
            self.resume_button,
            *self.mirror_flags.values(),
        ):
            widget.setEnabled(idle)
        self.start_button.setText("Resume remaining" if self.resume_mode else "Download missing")
        self.start_button.setEnabled(idle and pending > 0)
        self.selected_button.setEnabled(idle and bool(self.table.selectionModel().selectedRows()))
        self.select_all_button.setEnabled(idle and bool(self.model.hashes))
        self.retry_button.setEnabled(
            idle
            and any(
                self.model.states.get(h, {}).get("state") == "Failed" for h in self.model.hashes
            )
        )
        self.cancel_button.setEnabled(not idle and not self.job.stop.is_set())

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Save archives and queue here", self.directory.text() or self.app._directory()
        )
        if path:
            if path != self.directory.text():
                self.reset_states()
            self.directory.setText(path)

    def resume_queue(self):
        if self.job:
            return
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose the folder containing a saved queue",
            self.directory.text() or self.app._directory(),
        )
        if not path:
            return
        self.restore_queue(path)

    def restore_queue(self, path):
        if self.job or self._closed:
            return
        self.job = Job(lambda stop, _progress: load_download_progress(path, stop))
        self.phase = "restore"
        self.restore_directory = path
        self.job.signals.finished.connect(self.worker_finished)
        self.progress.setRange(0, 0)
        self.status.setText("Restoring saved queue…")
        self.controls()
        self.app.pool.start(self.job)

    def start(self, selected=False, retry=False):
        if self.job or self._closed:
            return
        hashes = (
            [index.data(HASH_ROLE) for index in self.table.selectionModel().selectedRows()]
            if selected
            else list(self.model.hashes)
        )
        if retry:
            hashes = [h for h in hashes if self.model.states.get(h, {}).get("state") == "Failed"]
        if not hashes:
            self.status.setText("No missing maps in this selection.")
            return
        directory = Path(self.directory.text()).expanduser()
        mirrors = tuple(m for m in self.mirrors if self.mirror_flags[m.name].isChecked())
        if not self.directory.text() or not directory.is_dir():
            self.status.setText("Choose an existing download folder first.")
            return
        if not mirrors:
            self.status.setText("Enable at least one download mirror.")
            return
        if not any(m.lookup for m in mirrors) and not self.official_api.isChecked():
            self.status.setText(
                "Enable an MD5 lookup mirror: "
                + ", ".join(m.name for m in self.mirrors if m.lookup)
            )
            return
        self.app.settings.setValue("downloads/directory", str(directory.resolve()))
        self.app.settings.setValue("downloads/use-official-api", self.official_api.isChecked())
        self.downloader.official_lookup = None
        if self.official_api.isChecked():
            from tools.osu_credentials import CredentialStore
            from tools.osu_lookup import OfficialLookup

            if getattr(self.app, "osu_api_lookup", None) is None:
                self.app.osu_api_lookup = OfficialLookup(
                    lambda: (
                        getattr(self.app, "osu_api_credentials", None) or CredentialStore().load()
                    )
                )
            self.downloader.official_lookup = self.app.osu_api_lookup
        self.downloader.mirrors = mirrors
        downloader, events, disposed = self.downloader, self.events, self.disposed

        def emit(event):
            while not disposed.is_set():
                try:
                    events.put((job.token, event), timeout=0.1)
                    return
                except queue.Full:
                    continue
            job.stop.set()

        job = Job(
            lambda stop, _progress: downloader.run(
                hashes,
                directory,
                emit,
                stop,
                **({"retry_failed": True} if retry or selected else {}),
            ),
            handles_cancellation=True,
        )
        self.job, self.phase = job, "download"
        self.terminal = None
        self.prepared = False
        self.completed, self.total = 0, len(hashes)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.status.setText("Checking saved downloads and installed songs before resuming…")
        self.job.signals.finished.connect(self.worker_finished)
        self.controls()
        self.app.pool.start(self.job)

    @Slot(object)
    def worker_finished(self, outcome):
        if self._closed or not self.job or outcome[0] != self.job.token:
            return
        self.terminal = outcome
        self.pump()

    def pump(self):
        if self._closed or not self.job:
            return
        for _ in range(250):
            try:
                token, event = self.events.get_nowait()
            except queue.Empty:
                break
            if token != self.job.token:
                continue
            self.apply_event(event)
        self.controls()
        if self.terminal is not None and self.events.empty():
            self.complete(self.terminal)

    def apply_event(self, event):
        if self._closed or self.job is None:
            return
        kind, checksum = event["kind"], event.get("hash")
        if kind == "snapshot":
            self.prepared = True
            self.total = event["remaining"]
            self.progress.setRange(0, max(1, self.total))
            for h in event["hashes"]:
                self.model.states.pop(h, None)
            for h, state in event["states"].items():
                self.model.states[h] = state
                if state["state"] == "Ready":
                    self.remember_ready(h, state)
            self.model.replace(self.model.hashes)
            self.status.setText(
                f"{self.total:,} remaining in this run. Failed entries wait for Retry failed."
            )
        elif kind in ("item", "result"):
            self.model.states.setdefault(checksum, {}).update(event)
            if kind == "result":
                if not self.prepared:
                    self.prepared = True
                    self.progress.setRange(0, max(1, self.total))
                self.completed += 1
                self.progress.setValue(self.completed)
                if event["state"] == "Ready":
                    self.remember_ready(checksum, event)
            self.status.setText(
                f"{self.completed:,}/{self.total:,} complete · {event.get('state', '')}"
            )
        elif kind == "metadata":
            details = {**event["details"], "Available": False}
            self.model.metadata[checksum] = details
            if self.app.workspace is self.workspace:
                self.workspace.beatmaps[checksum] = details
        elif kind == "bytes":
            self.status.setText(
                f"{event['mirror']} · {event['received'] / 2**20:.1f} MiB · "
                f"{self.completed:,}/{self.total:,} complete"
            )
        elif kind == "log":
            self.status.setText(event["message"])
        if checksum:
            self.model.changed(checksum)

    def remember_ready(self, checksum, result):
        installed = result.get("installed", False)
        details = {**result["details"], "Available": installed}
        self.model.metadata[checksum] = details
        if self.app.workspace is self.workspace:
            if installed:
                self.workspace.present_hashes.add(checksum)
                self.workspace.downloaded.pop(checksum, None)
            else:
                self.workspace.downloaded[checksum] = result["file"]
            self.workspace.beatmaps[checksum] = details

    def complete(self, outcome):
        _token, report, error = outcome
        stopped, phase = self.job.stop.is_set(), self.phase
        self.job = self.terminal = None
        if phase == "restore":
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            if stopped or isinstance(error, Cancelled):
                self.status.setText("Queue restore cancelled.")
            elif error:
                self.status.setText(str(error))
            elif report is None:
                self.status.setText(
                    "This folder has no saved download queue. Choose its original folder."
                )
            else:
                self.directory.setText(self.restore_directory)
                self.app.settings.setValue("downloads/directory", self.restore_directory)
                self.saved_hashes = report["hashes"]
                self.report_path = None
                self.model.states.clear()
                if self.scope.findText(SAVED_SCOPE) < 0:
                    self.scope.addItem(SAVED_SCOPE)
                self.scope.setCurrentText(SAVED_SCOPE)
                if any(m.lookup and m.name in report["mirrors"] for m in self.mirrors):
                    for name, check in self.mirror_flags.items():
                        check.setChecked(name in report["mirrors"])
                self.resume_mode = True
                self.scan()
                self.model.states.update(report["failed"])
                for checksum in self.model.hashes:
                    if checksum in report["completed"]:
                        result = report["completed"][checksum]
                        self.model.states[checksum] = result
                        self.remember_ready(checksum, result)
                self.model.replace(self.model.hashes)
                done = sum(h in report["completed"] for h in self.model.hashes)
                self.status.setText(
                    f"Saved queue restored: {done:,} already downloaded. "
                    "Resume remaining skips unchanged completed archives."
                    + (
                        " Older records need a one-time verification."
                        if report["legacy_index"]
                        else ""
                    )
                )
                self.details.setPlainText(
                    "Keep this folder’s archives and download records together. "
                    "Downloaded archives are ready to import; "
                    "Already installed means an exact .osu match."
                )
        elif error:
            self.status.setText("Download did not complete. Finished archives remain saved.")
            self.details.setPlainText(str(error))
            self.error(error)
        else:
            self.report_path = report["report_path"]
            ready, pending, failed, installed = download_counts(
                self.model.hashes, self.model.states
            )
            self.resume_mode = True
            self.status.setText(
                ("Paused. " if report.get("cancelled") else "")
                + f"{ready - installed:,} downloaded; {installed:,} installed; "
                + f"{pending:,} remaining; {failed:,} failed (Retry failed only). Queue saved."
            )
            if report.get("preparation_cancelled"):
                self.phase = "unchecked"
                self.status.setText(
                    "Paused during saved-queue checks. Resume to restore counts; "
                    "no downloads were retried."
                )
            self.details.setPlainText(
                "Report: "
                + self.report_path
                + "\nReports are kept in app data; only the latest 10 are retained. "
                "Verified archives are ready to import into osu!. "
                "The interrupted archive restarts when resumed."
            )
        self.controls()
        if self.close_requested:
            self.close()

    def selection_changed(self, *_args):
        selected = self.table.selectionModel().selectedRows()
        if len(selected) == 1:
            checksum = selected[0].data(HASH_ROLE)
            state = self.model.states.get(checksum, {})
            self.details.setPlainText(
                "MD5: "
                + checksum
                + "\n"
                + state.get("message", state.get("file", state.get("state", "Queued")))
            )
        elif selected:
            self.details.setPlainText(
                f"{len(selected):,} maps selected. Download selected keeps the same "
                "MD5 verification and fallback checks."
            )
        self.controls()

    def cancel(self):
        if self.job:
            self.job.stop.set()
            self.status.setText(
                "Stopping… Completed archives and the queue stay saved. "
                "The current network read may take up to 15 seconds."
            )
            self.controls()

    def can_close(self):
        if self.job:
            self.close_requested = True
            self.cancel()
            return False
        self.pump_timer.stop()
        return True
