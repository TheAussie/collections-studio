"""Shared Qt Widgets appearance and controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

STYLE = """
QWidget { background: #1b1b20; color: #e9e7ed; }
QMainWindow, QWidget#canvas { background: #18181d; }
QLabel { background: transparent; }
QLabel#brand { font-size: 18pt; font-weight: 650; }
QLabel#heading { font-size: 20pt; font-weight: 600; }
QLabel#section { font-weight: 600; }
QLabel#muted { color: #a3a0ad; }
QLabel#badge { background: #35303f; color: #d3c6e8; border-radius: 5px; padding: 5px 10px; }
QFrame#panel { background: #202026; border-radius: 9px; }
QFrame#workcopy { background: #222128; border-radius: 7px; }
QPushButton, QToolButton { background: #2d2c34; border: 1px solid transparent;
    border-radius: 5px; padding: 8px 13px; min-height: 18px; }
QPushButton:hover, QToolButton:hover { background: #3a3743; }
QPushButton:focus, QToolButton:focus { border: 1px solid #aa93c4; }
QPushButton#primary { background: #85719f; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background: #9580af; }
QPushButton#quiet { background: transparent; color: #b9b4c3; }
QPushButton#danger { background: transparent; color: #d5a7ae; }
QPushButton:disabled, QToolButton:disabled { color: #716e7b; background: #25242b; }
QLineEdit, QComboBox { background: #292830; border: 1px solid transparent;
    border-radius: 5px; padding: 9px 11px; selection-background-color: #655477; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #8e79a6; }
QTableView { background: #202026; alternate-background-color: #222229; border: none;
    selection-background-color: #3b3348; selection-color: #faf8ff; outline: none; }
QTableView::item { padding: 0px 10px; border-bottom: 1px solid #29282f; }
QTableView::item:focus { border: 1px solid #8e79a6; }
QHeaderView::section { background: #202026; color: #9e99a9; border: none;
    border-bottom: 1px solid #36323e; padding: 12px 10px; font-size: 8pt; font-weight: 600; }
QPlainTextEdit { background: #202026; border: none; color: #bbb6c6; }
QSplitter::handle { background: #18181d; width: 12px; height: 12px; }
QMenu { background: #292730; border: 1px solid #40394b; padding: 5px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #494057; }
QMenu::item:disabled { color: #827c8e; }
QToolTip { background: #302b39; color: #ece6f4; border: 1px solid #5f506f; padding: 7px; }
QProgressBar { background: #2b2932; border: none; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #9982b5; }
QScrollBar:vertical { background: #202026; width: 11px; }
QScrollBar::handle:vertical { background: #4b4557; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""


def label(text="", name="muted"):
    result = QLabel(text)
    result.setObjectName(name)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


def button(text, action, name=""):
    result = QPushButton(text)
    result.setObjectName(name)
    result.setAutoDefault(False)
    result.clicked.connect(action)
    return result
