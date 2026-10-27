"""Shared lifetime and file-opening behavior for the Qt collection dialogs."""

import threading
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QMessageBox


def finish_shutdown(window):
    """Join cancelled workers and destroy views while QApplication is still alive."""
    window.pool.waitForDone()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class StudioDialog(QDialog):
    def __init__(self, app, title):
        super().__init__(app)
        self.app = app
        self.workspace = app.workspace
        self._closed = False
        self.disposed = threading.Event()
        disposed = self.disposed
        self.destroyed.connect(lambda: disposed.set())
        self.setWindowTitle(title + " · Collections Studio")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def can_close(self):
        return True

    def _request_close(self):
        if self._closed:
            return True
        if not self.can_close():
            return False
        self._closed = True
        self.disposed.set()
        return True

    def reject(self):
        if self._request_close():
            super().reject()

    def accept(self):
        self.reject()

    def closeEvent(self, event):
        if self._request_close():
            super().closeEvent(event)
        else:
            event.ignore()

    def error(self, error):
        QMessageBox.critical(self, "Collections Studio", str(error))

    def open_folder(self, path):
        folder = Path(path).resolve()
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
