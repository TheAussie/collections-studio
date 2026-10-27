# Native portable builds. One-file mode extracts Qt/.NET libraries at runtime.
import os
import sys
from pathlib import Path

root = Path(SPECPATH).parent
stage = Path(os.environ["COLLECTIONS_STUDIO_STAGE"])
onefile = os.environ.get("COLLECTIONS_STUDIO_ONEFILE") == "1"
helper = stage / "backend" / ("realm-collection-import.exe" if sys.platform == "win32" else "realm-collection-import")
a = Analysis(
    [str(root / "tools" / "qt_collection_studio.py")],
    pathex=[str(root)],
    # BINARY preserves the executable bit when the helper is unpacked on Linux.
    binaries=[(str(helper), "backend")],
    datas=[(str(stage / "backend"), "backend"), (str(stage / "notices"), "notices")],
    hiddenimports=[],
    hookspath=[],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "flask", "gunicorn", "PIL", "requests"],
    noarchive=False,
)
# Avoid packing a second DATA entry for the executable classified as BINARY above.
a.datas = [entry for entry in a.datas if Path(entry[1]).resolve() != helper.resolve()]
pyz = PYZ(a.pure)
options = dict(name="CollectionsStudio", debug=False, strip=False, upx=False, console=False)
if onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, **options)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CollectionsStudio")
