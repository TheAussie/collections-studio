"""Review a destination and duplicate counts before one in-memory transfer."""

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QVBoxLayout

from tools.qt_style import button, label


class TransferDialog(QDialog):
    def __init__(self, app, source_id, hashes, *, move=False):
        super().__init__(app)
        self.workspace, self.source_id = app.workspace, source_id
        self.hashes = tuple(dict.fromkeys(value.lower() for value in hashes))
        self.move = move
        verb = "Move" if move else "Copy"
        self.setWindowTitle(f"{verb} selected maps · Collections Studio")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label(f"{verb} {len(self.hashes):,} selected beatmaps", "heading"))
        source = self.workspace.collection(source_id)
        source_label = label(f"From: {source['Name']}")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        layout.addWidget(label("Destination collection", "section"))
        self.target = QComboBox()
        self.target.setAccessibleName("Destination collection")
        counts = Counter(group["Name"] for group in self.workspace.collections)
        for number, group in enumerate(self.workspace.collections, 1):
            if group["Id"] != source_id:
                name = group["Name"]
                if counts[name] > 1:
                    name += f" (collection {number})"
                self.target.addItem(name, group["Id"])
        layout.addWidget(self.target)
        self.summary = label()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        note = label(
            "Maps already in the destination are skipped. "
            + (
                "Selected memberships leave only the source collection."
                if move
                else "Selected memberships stay in the source collection."
            )
            + " Undo is available. Changes stay in memory until Save; beatmap files stay in place."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.cancel_button = button("Cancel", self.reject, "quiet")
        self.apply_button = button(verb + " selected", self.accept, "primary")
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self.target.currentIndexChanged.connect(self.update_summary)
        self.update_summary()

    def update_summary(self):
        target_id = self.target.currentData()
        self.apply_button.setEnabled(target_id is not None)
        if target_id is None:
            self.summary.setText("Create another collection first.")
            return
        target = self.workspace.collection(target_id)
        known = {value.lower() for value in target["Hashes"]}
        duplicate_count = len(set(self.hashes) & known)
        self.summary.setText(
            f"{len(self.hashes) - duplicate_count:,} new additions · "
            f"{duplicate_count:,} already in the destination"
        )
