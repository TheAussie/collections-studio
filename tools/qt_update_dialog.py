"""A single download-and-restart action backed by the portable executable itself."""

import shutil

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from tools.app_updates import check_for_update, download_update
from tools.beatmap_downloads import Cancelled
from tools.qt_dialog_support import StudioDialog
from tools.qt_jobs import Job
from tools.qt_style import button, label
from tools.update_install import create_stage, portable_target, start_helper


class UpdateDialog(StudioDialog):
    def __init__(self, app, available=None):
        super().__init__(app, "Update Collections Studio")
        self.info, self.job, self.stage = available, None, None
        self.phase, self.closing = "idle", False
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("Collections Studio updates", "heading"))
        layout.addWidget(label(f"Installed version: {app.version}"))
        self.status = label("Checking GitHub releases…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText("Release notes appear here.")
        layout.addWidget(self.notes, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.automatic = QCheckBox("Check for updates when the app starts")
        self.automatic.setChecked(app.settings.value("updates/check-on-startup", True, type=bool))
        self.automatic.toggled.connect(self._automatic_changed)
        layout.addWidget(self.automatic)
        actions = QHBoxLayout()
        self.close_button = button("Close", self.close, "quiet")
        self.check_button = button("Check again", self.check)
        self.install_button = button("Download and restart", self.install, "primary")
        actions.addWidget(self.close_button)
        actions.addStretch()
        actions.addWidget(self.check_button)
        actions.addWidget(self.install_button)
        layout.addLayout(actions)
        if available:
            self._checked(available)
        else:
            self.check()

    def _automatic_changed(self, enabled):
        self.app.settings.setValue("updates/check-on-startup", enabled)
        self.app.settings.sync()

    def check(self):
        self._start("check", lambda stop, _progress: check_for_update(self.app.version, stop=stop))

    def _checked(self, info):
        self.info = info
        self.status.setText(
            f"Version {info.version} is available ({info.size / 1024**2:.1f} MiB)."
            if info
            else "You’re up to date. No newer stable release is available."
        )
        self.notes.setPlainText(info.notes if info else "")
        self.install_button.setEnabled(info is not None)

    def install(self):
        if self.job or self.app.job or not self.info:
            return
        try:
            target = portable_target()
        except ValueError as error:
            self.status.setText(str(error))
            return
        workspace = self.app.workspace
        if workspace and (workspace.dirty or not workspace.source_path):
            answer = QMessageBox.warning(
                self,
                "Save changes before updating?",
                "Save your current collection changes before restarting?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save:
                self.app.save(after=lambda: self.install() if not self._closed else None)
                return
        self.target = target
        info = self.info

        def download(stop, progress):
            stage = create_stage(target)
            self.stage = stage
            try:
                return download_update(info, stage, stop=stop, progress=progress)
            except Exception:
                shutil.rmtree(stage)
                self.stage = None
                raise

        self._start("download", download)

    def _start(self, phase, work):
        if self.job or self._closed:
            return
        self.phase = phase
        self.job = Job(work)
        self.job.signals.finished.connect(self._finished)
        self.job.signals.progress.connect(self._progress)
        self.progress.show()
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.close_button.setText("Cancel")
        self.close_button.setEnabled(phase != "handoff")
        self.status.setText(
            {
                "check": "Checking GitHub releases…",
                "download": "Downloading and verifying the update…",
                "handoff": "Preparing to close and replace this client…",
            }[phase]
        )
        QThreadPool.globalInstance().start(self.job)

    @Slot(str, str)
    def _progress(self, token, message):
        if not self._closed and self.job and token == self.job.token:
            self.status.setText(message)

    @Slot(object)
    def _finished(self, outcome):
        token, result, error = outcome
        if self._closed or not self.job or token != self.job.token:
            return
        cancelled = self.job.stop.is_set() or isinstance(error, Cancelled)
        self.job = None
        self.progress.hide()
        self.check_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.close_button.setText("Close")
        if cancelled or error:
            self.status.setText(
                "Update cancelled. The current client is unchanged."
                if cancelled
                else f"Update could not complete: {error}"
            )
            self.install_button.setEnabled(self.info is not None)
            self.phase = "idle"
            if self.closing:
                self.close()
            return
        if self.phase == "check":
            self._checked(result)
        elif self.phase == "download":
            open_file = self.app.workspace.source_path if self.app.workspace else ""
            self._start(
                "handoff",
                lambda stop, _progress: start_helper(
                    self.stage, self.target, result, self.info.version, open_file, stop=stop
                ),
            )
        elif self.phase == "handoff":
            self.phase = "ready"
            self.close()
            self.app.restart_after_update()

    def can_close(self):
        if self.job:
            if self.phase != "handoff":
                self.closing = True
                self.job.stop.set()
                self.status.setText("Cancelling update…")
            return False
        return True
