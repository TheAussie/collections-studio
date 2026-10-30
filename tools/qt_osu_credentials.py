"""Explicit user-owned OAuth credential setup, with optional native-vault storage."""

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout

from tools.osu_credentials import CredentialError, CredentialStore, validate
from tools.qt_dialog_support import StudioDialog
from tools.qt_jobs import Job
from tools.qt_style import button, label


class OsuCredentialsDialog(StudioDialog):
    def __init__(self, app, store=None):
        super().__init__(app, "osu! API credentials")
        self.store = store or CredentialStore()
        self.job = None
        self.resize(570, 330)
        layout = QVBoxLayout(self)
        help_text = label(
            "Optional fallback for missing-map MD5 lookup. Create your own OAuth application at "
            "osu.ppy.sh/home/account/edit#oauth. Enter its client ID and secret, "
            "not your osu! password. No browser redirect or user login is required."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.client_id = QLineEdit(str(app.settings.value("osu-api/client-id", "")))
        self.client_id.setMaxLength(20)
        self.client_id.setAccessibleName("osu! API client ID")
        self.client_id.setPlaceholderText("Numeric client ID")
        layout.addWidget(self.client_id)
        self.secret = QLineEdit()
        self.secret.setMaxLength(512)
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setAccessibleName("osu! API client secret")
        self.secret.setPlaceholderText("Client secret (leave blank to use saved credentials)")
        layout.addWidget(self.secret)
        self.status = label(
            "Save uses Windows Credential Manager or Linux Secret Service. "
            "Secrets are never put in settings or download reports."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.buttons = [
            button("Save and use", lambda: self.start("save"), "primary"),
            button("Use this session only", lambda: self.start("session")),
            button("Forget saved credentials", lambda: self.start("delete")),
        ]
        for control in self.buttons:
            row.addWidget(control)
        layout.addLayout(row)

    def can_close(self):
        return self.job is None

    def start(self, action):
        if self.job:
            return
        client_id, secret = self.client_id.text(), self.secret.text()
        try:
            if action != "delete" and secret:
                validate(client_id, secret)
        except CredentialError as error:
            self.status.setText(str(error))
            return

        def work(_stop, _progress):
            if action == "delete":
                self.store.delete()
                return None
            pair = validate(client_id, secret) if secret else self.store.load()
            if pair is None or pair[0] != client_id.strip():
                raise CredentialError(
                    "Enter the client ID and secret, or use the ID of the saved credentials."
                )
            if action == "save":
                self.store.save(*pair)
            return pair

        self.job = Job(work)
        self.job.signals.finished.connect(self.finished_operation)
        for control in self.buttons:
            control.setEnabled(False)
        self.status.setText("Applying credentials…")
        self.app.pool.start(self.job)

    def finished_operation(self, outcome):
        token, pair, error = outcome
        if self._closed or not self.job or self.job.token != token:
            return
        self.job = None
        for control in self.buttons:
            control.setEnabled(True)
        if error:
            self.status.setText(
                str(error)
                if isinstance(error, CredentialError)
                else "The credential store could not complete the operation."
            )
            return
        self.app.osu_api_credentials = pair
        self.app.osu_api_lookup = None
        if pair:
            self.app.settings.setValue("osu-api/client-id", pair[0])
        else:
            self.app.settings.remove("osu-api/client-id")
            self.app.settings.setValue("downloads/use-official-api", False)
        self.secret.clear()
        self.accept()
