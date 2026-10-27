"""Worker results reach QObject slots through queued signals; cancellation is cooperative."""

import threading
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, Signal

from tools.beatmap_downloads import Cancelled


class JobSignals(QObject):
    finished = Signal(object)
    progress = Signal(str, str)


class Job(QRunnable):
    def __init__(self, work, *, handles_cancellation=False):
        super().__init__()
        self.token = uuid4().hex
        self.stop = threading.Event()
        self.signals = JobSignals()
        self.work = work
        self.handles_cancellation = handles_cancellation

    def run(self):
        result, error = None, None
        try:
            if self.stop.is_set() and not self.handles_cancellation:
                raise Cancelled()
            result = self.work(self.stop, lambda text: self.signals.progress.emit(self.token, text))
            if self.stop.is_set() and not self.handles_cancellation:
                raise Cancelled()
        except Exception as caught:
            error = caught
        self.signals.finished.emit((self.token, result, error))
