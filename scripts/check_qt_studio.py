"""Render the Qt preview using a supplied test archive, never a live osu! database."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QSettings, qVersion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.beatmap_downloads import inspect_archive  # noqa: E402
from tools.qt_collection_studio import StudioWindow, configure_appearance  # noqa: E402
from tools.stable_collections import encode  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "qt-studio-review")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = inspect_archive(args.archive)
    hashes = list(metadata)
    unresolved = "3151f10743f5e6ff0081bec80741972d"
    app = QApplication([])
    app.setApplicationName("CollectionsStudioQA")
    configure_appearance(app)
    window = StudioWindow(
        settings=QSettings(str(output / "settings.ini"), QSettings.Format.IniFormat)
    )
    window.resize(1360, 900)
    window.show()
    app.processEvents()
    images = []

    def capture(name):
        app.processEvents()
        path = output / name
        assert window.grab().save(str(path))
        images.append(str(path))

    capture("main-screen.png")
    source = output / "fixture collection.db"
    data = encode(
        [
            {"Name": "Archive sample", "Hashes": hashes},
            {"Name": "Missing & unresolved", "Hashes": hashes[-2:] + [unresolved]},
            {"Name": "Practice 練習", "Hashes": []},
        ]
    )
    source.write_bytes(data)
    window.load_path(str(source))
    deadline = time.monotonic() + 10
    while window.job and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not window.job
    window.workspace.beatmaps = metadata
    window.workspace.present_hashes = set(hashes[:-2])
    window.show_collection()
    window.maps.selectRow(0)
    capture("populated-collection.png")
    window.selected = next(
        g["Id"] for g in window.workspace.collections if g["Name"] == "Missing & unresolved"
    )
    window.refresh_collections()
    window.maps.selectRow(2)
    capture("missing-unresolved.png")
    window.resize(1000, 700)
    app.processEvents()
    window.maps.scrollTo(window.map_model.index(2, 0))
    controls = (
        window.open_button,
        window.import_button,
        window.tools_button,
        window.save_button,
        window.rename_button,
        window.delete_button,
        window.new_button,
        window.remove_button,
    )
    for control in controls:
        position = control.mapTo(window, QPoint(0, 0))
        assert position.x() >= 0 and position.y() >= 0
        assert position.x() + control.width() <= window.width()
        assert position.y() + control.height() <= window.height()
    capture("compact.png")
    report = {
        "Qt": qVersion(),
        "PlatformPlugin": app.platformName(),
        "DevicePixelRatio": window.devicePixelRatio(),
        "Images": images,
        "MetadataSource": str(args.archive.resolve()),
        "NoBundledMetadataOrArtwork": True,
        "OriginalFixtureUnchanged": source.read_bytes() == data,
        "FixtureSha256": hashlib.sha256(data).hexdigest(),
        "Statuses": [window.map_model.index(row, 3).data() for row in range(3)],
        "ControlsFitAt1000x700": True,
    }
    (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    window.close()
    app.processEvents()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
