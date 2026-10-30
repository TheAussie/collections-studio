# Collections Studio on Linux

Choose one download: `CollectionsStudio-linux-x64.AppImage` for an AppImage with
an icon/desktop entry, or `CollectionsStudio-linux-x64` for the existing standalone
executable. Both include Python, Qt and the Realm helper; no Python/.NET installation
is needed. x86-64 Linux is required. Builds target Ubuntu 22.04 or newer; other
Linux distributions require testing rather than an assumption of compatibility.

## Run the AppImage without root

```sh
mkdir -p "$HOME/Applications"
mv "$HOME/Downloads/CollectionsStudio-linux-x64.AppImage" "$HOME/Applications/"
chmod +x "$HOME/Applications/CollectionsStudio-linux-x64.AppImage"
"$HOME/Applications/CollectionsStudio-linux-x64.AppImage"
```

Verify the download with the release's SHA256SUMS before running it. If FUSE is
unavailable, use the runtime's extraction fallback (needs temporary disk space):

```sh
APPIMAGE_EXTRACT_AND_RUN=1 "$HOME/Applications/CollectionsStudio-linux-x64.AppImage"
```

For an application-menu shortcut, create
`~/.local/share/applications/collections-studio.desktop` with the following content,
replacing `/home/YOUR_USER` with your actual home directory:

```ini
[Desktop Entry]
Type=Application
Name=Collections Studio
Exec="/home/YOUR_USER/Applications/CollectionsStudio-linux-x64.AppImage"
Icon=applications-games
Terminal=false
Categories=Game;Utility;
```

No system install or root-owned directory is required. An AppImage is a portable
application, not a sandbox. This first AppImage wraps the already verified portable
payload: it extracts twice at startup and needs extra temporary space. It does not
by itself fix incompatible host Fontconfig/XKB configuration. Font/keyboard warnings
still need a separate compatibility fix and testing on the affected distribution.

## Updates and removal

The standalone executable retains its built-in download/replace/restart updater.
For this initial AppImage, download the new AppImage, verify it, close the app and
replace the old file in ~/Applications, then mark it executable. Automatic replacement
is disabled for AppImages so an update cannot overwrite a temporary extracted payload.
Remove the AppImage and shortcut to uninstall; your collections and settings are not
removed. Game databases are edited only through the app's existing explicit Save flow.

## Credits and rebuilding

Keep `CollectionsStudio-sources-and-notices.zip` available with redistributions.
It contains the original application/Qt sources and platform notices, plus AppImage
runtime sources, dependency sources/licences, the packaging lock and build receipt.
To rebuild the image, run the release build/staging commands in docs/releases.md,
then `python desktop/package_appimage.py --input artifacts/release --cache /tmp/cs-appimage-cache`.
The pinned appimagetool supplies its own matching type-2 runtime; its source and
static dependency sources are retained. To replace/relink that runtime, rebuild it
from the included type2-runtime source/build recipes and dependencies, extract the
AppImage with `--appimage-extract`, then use appimagetool with
`--runtime-file /path/to/rebuilt/runtime squashfs-root New.AppImage`.
