"""Qt item models: no cell widgets, exact original hashes remain the row identity."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from tools.beatmap_downloads import Cancelled

HASH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
IDENTITY_ROLE = int(Qt.ItemDataRole.UserRole) + 2
ROOT_INDEX = QModelIndex()


def map_values(checksum, metadata, present, downloaded=None):
    details = metadata.get(checksum.lower(), {})
    title = details.get("Title") or "Unresolved beatmap"
    artist = details.get("Artist")
    identified = any(
        details.get(key) for key in ("Title", "Artist", "Difficulty", "BeatmapId", "SetId")
    )
    state = (
        "Available"
        if checksum.lower() in present
        else "Downloaded"
        if checksum.lower() in (downloaded or {})
        else "Missing"
        if identified
        else "Unresolved"
    )
    return (
        f"{artist} — {title}" if artist else title,
        details.get("Difficulty") or "—",
        details.get("Mode") or "—",
        state,
    )


def map_order(hashes, metadata, present, query, status, column, descending, stop, downloaded=None):
    """Search/sort large collections in a worker using immutable membership snapshots."""
    query = query.casefold().strip()
    rows = []
    for index, checksum in enumerate(hashes):
        if index % 256 == 0 and stop.is_set():
            raise Cancelled()
        values = map_values(checksum, metadata, present, downloaded)
        if status != "All maps" and values[3] != status:
            continue
        if query and query not in (" ".join(map(str, values)) + " " + checksum).casefold():
            continue
        rows.append((str(values[column]).casefold() if column >= 0 else index, index))
    if stop.is_set():
        raise Cancelled()
    if column >= 0:
        rows.sort(key=lambda item: item[0], reverse=descending)
    if stop.is_set():
        raise Cancelled()
    return [index for _key, index in rows]


class CollectionModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups = []

    def replace(self, groups):
        self.beginResetModel()
        self.groups = groups
        self.endResetModel()

    def rowCount(self, parent=ROOT_INDEX):
        return 0 if parent.isValid() else len(self.groups)

    def columnCount(self, parent=ROOT_INDEX):
        return 0 if parent.isValid() else 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("COLLECTION", "MAPS")[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.groups):
            return None
        group = self.groups[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return group["Name"] if index.column() == 0 else f"{len(group['Hashes']):,}"
        if role == IDENTITY_ROLE:
            return group["Id"]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{group['Name']}\n{len(group['Hashes']):,} memberships"
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 1:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None


class BeatmapModel(QAbstractTableModel):
    sort_requested = Signal(int, object)
    HEADERS = ("BEATMAP", "DIFFICULTY", "MODE", "STATUS")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hashes, self.order = (), []
        self.metadata, self.present = {}, set()
        self.downloaded = {}

    def replace(self, hashes, metadata, present, order=None, downloaded=None):
        self.beginResetModel()
        self.hashes = tuple(hashes)
        self.metadata, self.present = metadata, present
        self.downloaded = downloaded or {}
        self.order = list(range(len(hashes))) if order is None else order
        self.endResetModel()

    def reorder(self, order):
        self.beginResetModel()
        self.order = order
        self.endResetModel()

    def rowCount(self, parent=ROOT_INDEX):
        return 0 if parent.isValid() else len(self.order)

    def columnCount(self, parent=ROOT_INDEX):
        return 0 if parent.isValid() else 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.order):
            return None
        checksum = self.hashes[self.order[index.row()]]
        if role == HASH_ROLE:
            return checksum
        values = map_values(checksum, self.metadata, self.present, self.downloaded)
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join([values[0], values[1], "MD5: " + checksum, values[3]])
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
            return QColor(
                {
                    "Available": "#a8c2b3",
                    "Downloaded": "#c9b7db",
                    "Missing": "#d1bda5",
                    "Unresolved": "#bbb0cf",
                }[values[3]]
            )
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.sort_requested.emit(column, order)
