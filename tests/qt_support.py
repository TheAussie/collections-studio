"""One QApplication lifetime for Qt tests and explicit disposal of each view."""

import pytest


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    yield application
    QThreadPool.globalInstance().waitForDone(10000)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def dispose(window):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
