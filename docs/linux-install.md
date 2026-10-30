# Collections Studio on Linux

Choose `CollectionsStudio-linux-x64` (standalone binary) or
`CollectionsStudio-linux-x64.AppImage`. Both contain Python, Qt and the Realm helper;
no Python/.NET installation is needed. Both support the same built-in per-user
installation and uninstall controls since v0.1.5. Windows remains a portable
EXE; this installer is Linux-only.

## Install for this user

1. Download your preferred Linux file and verify it with the release's SHA256SUMS.
2. Mark it executable in your file manager's Properties/Permissions, then launch it.
   You can also use `chmod +x /path/to/download` from a terminal.
3. Click **Install for this user…** in the window header, or open
   **Tools → Install / uninstall…**.
4. Review the destination, optionally select **Also create a desktop shortcut**, then
   click **Install for this user**.

The app copies itself to `$XDG_DATA_HOME/collections-studio/installation/CollectionsStudio`
(default `~/.local/share/collections-studio/installation/CollectionsStudio`), installs
its own SVG icon and creates the application-menu entry. Launch it from your menu
next time. The original download and current window stay intact. Either format uses
one installation and launcher, so switching formats does not create duplicates.
No administrator access or system package installation is involved.

Desktop shortcuts depend on your desktop environment. Some require **Allow Launching**,
and some do not display desktop icons. The application-menu entry is the default.
Existing custom launcher/icon files that are replaced are saved in the reported
`collections-studio/installation-backups` folder. Symlink conflicts are rejected.

## Uninstall

Open **Tools → Install / uninstall… → Uninstall…**, or the launcher's **Uninstall
Collections Studio…** action where your desktop exposes launcher actions. Review and
confirm removal. Only the managed executable and its registered icon/launchers are
removed. Modified or relocated shortcuts are preserved and listed in the result.

Collections, game files, downloaded archives/reports, cached song indexes, settings,
API credentials and the original downloaded executable are kept. The current app
window stays open; close it when finished. If uninstalling the running installed copy,
start the original download to install again. No separate background updater or
uninstall service is installed.

## Update or repair

The installed standalone binary retains its existing download/replace/restart updater.
AppImage automatic updates remain manual: launch the newer downloaded AppImage,
open **Tools → Install / uninstall…**, and choose **Update / repair installation**.
This also repairs the installed icon/menu entry and can switch between formats.

## Run portably instead

You can continue running either download without installing it. For an AppImage on a
system without FUSE, use:

```sh
APPIMAGE_EXTRACT_AND_RUN=1 /path/to/CollectionsStudio-linux-x64.AppImage
```

The original AppImage file must be available for built-in installation. Launching only
an extracted payload cannot install the outer image. Source Python checkouts expose
installation status/uninstall controls but cannot install Python as the application.

An AppImage is portable, not a sandbox. The current image wraps the one-file payload
and extracts twice at startup. Packaging alone does not fix host Fontconfig/XKB
configuration compatibility. Test the actual target distribution; Ubuntu 22.04 is the
current Linux build target.

## Credits and rebuilding

Keep `CollectionsStudio-sources-and-notices.zip` available with redistributions.
It retains application/Qt and AppImage runtime/dependency sources, notices, locks and
build receipts. The same app icon is bundled into the standalone binary and AppImage.
To rebuild, use docs/releases.md and `desktop/package_appimage.py`. To replace/relink
the AppImage runtime, rebuild the included type2-runtime/dependency sources, extract
with `--appimage-extract`, then use appimagetool with
`--runtime-file /path/to/rebuilt/runtime squashfs-root New.AppImage`.
