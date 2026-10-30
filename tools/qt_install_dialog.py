"""User-reviewed Linux integration and uninstall; no automatic installation."""

from PySide6.QtCore import QStandardPaths, Slot
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QMessageBox, QVBoxLayout

from tools import linux_install
from tools.qt_dialog_support import StudioDialog
from tools.qt_jobs import Job
from tools.qt_style import button, label


class InstallationDialog(StudioDialog):
    def __init__(self, app, *, layout=None, artifact=None):
        super().__init__(app, "Install / uninstall")
        self.resize(670, 440)
        self.job = None
        self.install_layout = layout or linux_install.user_layout(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        )
        self.artifact = artifact
        self.record = None
        self.source_error = ""
        if self.artifact is None:
            try:
                self.artifact = linux_install.running_artifact()
            except linux_install.InstallError as error:
                self.source_error = str(error)
        content = QVBoxLayout(self)
        content.addWidget(label("Install Collections Studio for this user", "section"))
        info = label(
            f"Running version: {self.app.version}\nApplication: {self.install_layout.binary}\n"
            f"Application-menu entry: {self.install_layout.launcher}\n"
            "The app and its proper icon are installed without administrator permissions. "
            "The original download stays where it is. "
            "Replaced custom launcher/icon files are backed up."
        )
        info.setWordWrap(True)
        content.addWidget(info)
        self.desktop = QCheckBox("Also create a desktop shortcut")
        self.desktop.setEnabled(self.install_layout.desktop is not None)
        self.desktop.setToolTip(
            "Some desktops require Allow Launching; some do not display desktop icons."
        )
        content.addWidget(self.desktop)
        self.status = label()
        self.status.setWordWrap(True)
        content.addWidget(self.status)
        preservation = label(
            "Uninstall removes only this managed app, icon and launchers. Collections, "
            "downloaded maps, caches, settings and saved API credentials are kept. "
            "This window will keep running until you close it."
        )
        preservation.setWordWrap(True)
        content.addWidget(preservation)
        content.addStretch()
        actions = QHBoxLayout()
        self.install_button = button(
            "Install for this user", lambda: self.start("install"), "primary"
        )
        self.uninstall_button = button("Uninstall…", lambda: self.start("uninstall"), "danger")
        self.close_button = button("Close", self.reject)
        actions.addWidget(self.install_button)
        actions.addWidget(self.uninstall_button)
        actions.addStretch()
        actions.addWidget(self.close_button)
        content.addLayout(actions)
        self.refresh()

    def refresh(self):
        try:
            if self.artifact is not None and not self.artifact.path.is_file():
                self.artifact = None
                self.source_error = "Start the original download if you want to install again."
            self.record = linux_install.installation(self.install_layout)
            self.install_button.setEnabled(self.artifact is not None and self.job is None)
            self.install_button.setText(
                "Update / repair installation" if self.record else "Install for this user"
            )
            self.uninstall_button.setEnabled(self.record is not None and self.job is None)
            message = (
                f"Installed: {self.record['version']} ({self.record['kind']})."
                if self.record
                else "No managed installation found."
            )
            if self.source_error:
                message += "\n" + self.source_error
            self.status.setText(message)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            self.install_button.setEnabled(False)
            self.uninstall_button.setEnabled(False)

    def can_close(self):
        return self.job is None

    def start(self, action):
        if self.job:
            return
        if action == "uninstall":
            answer = QMessageBox.question(
                self,
                "Uninstall Collections Studio?",
                f"Remove the managed application at {self.install_layout.binary} "
                "and its generated launchers/icon?\n\n"
                "Your collections, downloads, settings and credentials will be kept. "
                "The current window will remain open.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        elif self.artifact is None:
            return
        shortcut = self.desktop.isChecked()
        self.job = Job(
            lambda stop, _progress: (
                linux_install.install(
                    self.install_layout,
                    self.artifact,
                    self.app.version,
                    desktop=shortcut,
                    stop=stop,
                )
                if action == "install"
                else linux_install.uninstall(self.install_layout, stop=stop)
            )
        )
        self.action = action
        self.job.signals.finished.connect(self.finished_operation)
        for control in (
            self.install_button,
            self.uninstall_button,
            self.close_button,
            self.desktop,
        ):
            control.setEnabled(False)
        self.status.setText(
            "Installing…" if action == "install" else "Removing managed application files…"
        )
        self.app.pool.start(self.job)

    @Slot(object)
    def finished_operation(self, outcome):
        token, result, error = outcome
        if self._closed or self.job is None or self.job.token != token:
            return
        self.job = None
        self.close_button.setEnabled(True)
        self.desktop.setEnabled(self.install_layout.desktop is not None)
        self.refresh()
        if error:
            self.status.setText(str(error))
            return
        text = (
            "Installed. Open Collections Studio from your application menu. "
            "The current window stays open; your desktop may ask Allow Launching for its shortcut."
            if self.action == "install"
            else "Uninstalled. Your data is kept and this window stays open."
        )
        if result.get("backup"):
            text += "\nPrevious customized launcher/icon files: " + result["backup"]
        if result.get("kept"):
            text += "\nCustomized or relocated files left in place:\n" + "\n".join(result["kept"])
        self.status.setText(text)
        self.app.refresh_install_button()
