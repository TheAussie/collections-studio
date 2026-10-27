"""Read-only acknowledgements and licence viewer."""

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QTextBrowser, QVBoxLayout

from tools.credits import read_documents


class CreditsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Credits and licences — Collections Studio")
        self.resize(840, 640)
        self.setMinimumSize(540, 380)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        for title, text in read_documents():
            browser = QTextBrowser(self)
            browser.setOpenExternalLinks(True)
            if title == "Project licence":
                browser.setPlainText(text)
            else:
                browser.setMarkdown(text)
                # Qt's Markdown parser assigns blue directly, overriding link CSS.
                # Set anchor colours without changing their URLs or other formatting.
                document = browser.document()
                anchors = []
                block = document.begin()
                while block.isValid():
                    iterator = block.begin()
                    while not iterator.atEnd():
                        fragment = iterator.fragment()
                        if fragment.isValid() and fragment.charFormat().isAnchor():
                            anchors.append((fragment.position(), fragment.length()))
                        iterator += 1
                    block = block.next()
                colour = QTextCharFormat()
                colour.setForeground(QColor("#ffb49e"))
                for position, length in anchors:
                    cursor = QTextCursor(document)
                    cursor.setPosition(position)
                    cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
                    cursor.mergeCharFormat(colour)
            self.tabs.addTab(browser, title)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
