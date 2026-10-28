"""Keep standard Qt GUI support, without the unused GTK theme's dependency chain.

Collections Studio explicitly selects Fusion. X11, Wayland, image formats and
the desktop portal remain collected by the pinned upstream PyInstaller helper.
Only the Linux release spec uses this hook.
"""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in binaries if Path(entry[0]).name != "libqgtk3.so"]
