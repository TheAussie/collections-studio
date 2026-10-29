# Collections Studio

The main screen, download/resume queue, and format migration now use Qt Widgets.
The Tkinter entry point
`tools/collections-studio` remains runnable. The release workflow builds and runs
the mandatory packaged self-test natively on Windows x64 and Ubuntu Linux x64.
Manual acceptance with copied game databases and a clean Windows machine remains
separate from CI. First-party source is licensed under MIT.

## Run from source

Install Python 3.12+ and uv. For Realm files, also install .NET SDK 10.0.112 and
the .NET 8 runtime, or use a self-contained packaged helper. Use disposable copies
of game databases. Close osu! before making copies, especially `client.realm`.

```sh
uv sync --frozen --extra desktop
uv run --frozen --extra desktop python -m tools.qt_collection_studio
```

On Windows, the same commands work in PowerShell. No Bash launcher, Unix tools,
system `/usr/bin/python`, or Linux user paths are required by this Qt entry point.
Optional `--file "path with spaces/collection.db"` opens a file on startup.
The original interface remains `./tools/collections-studio` on Linux, or
`python -m tools.collection_studio` where a working Tk installation is present.

The interface supports open/new stable files, Realm inspection, collection
search/counts, new/rename/delete, multi-selection and membership removal, undo,
stable imports, Maps/osu!collector imports, inventory/cache reads, cancellable
Songs scans and verified saves with automatic backups. Qt model/view tables use no
cell widgets. Map filtering/sorting runs off the UI thread, with cancellation and
generation checks. Details retain full hashes and source paths. Unresolved hashes
stay in their collections. Existing duplicate, Unicode, stable version marker,
stale-source and Realm unrelated-table audits remain authoritative. Backups and
separate exports never overwrite an existing file.

In Qt, **Copy to…** / **Move to…** transfer selected difficulty memberships to
another collection, with a preview of new additions and existing MD5s. **Browse
songs** switches the current collection to the game library, including maps not
assigned to any collection. Realm supplies its indexed beatmaps automatically;
stable users load `osu!.db` or scan Songs using the inline buttons or Tools menu.
The browser initially shows Available maps not already in the target collection.
Turn off **Not already in this collection** to see membership indicators.
Duplicates are skipped by case-insensitive MD5; a move removes selected source
memberships after ensuring the destination contains them. Other memberships,
song files and existing legacy duplicates remain intact. Every operation supports
Undo and changes only the working session until Save. These new controls are in
Qt; the classic interface remains available with its existing features.

**Export…** (also **Tools → Export collection.db…**) creates one `collection.db`
containing **All collections** or checked rows under **Choose collections**.
Search preserves checks, and the summary counts every checked collection.
Both stable and lazer sessions support this export, including unsaved collection
edits. Choose a new filename or folder; existing files are never replaced.
The exported file is reopened and verified in the background. Export does not
switch databases, clear Undo, or mark unsaved changes as saved.

**Tools → Get missing maps…** checks the last import, current collection, all
collections, or a saved queue. Choose mirrors and an archive folder, then download
all missing maps or a selection. Cancel keeps verified archives and every pending
hash in the saved queue. **Resume queue…** restores that folder's queue after
reopening the app. Completed maps immediately show **Already downloaded**, with
their saved metadata. Unchanged archives reuse their verification record without
opening the ZIP, hashing its maps or contacting a mirror. Changed/missing files
return to the remaining work. Older records receive one verification pass to
upgrade them. Keep both hidden JSON files with the archives. Interrupted archives
restart from the beginning. The virtual table receives bounded batches
of progress events without creating a widget per map. Closing an active download
waits for cancellation and checkpoint cleanup. **Downloaded** means an archive
is ready for import; **Available** requires installed inventory after importing
it through osu! and refreshing the inventory.

**Tools → Migrate collections…** supports all, current, or manually selected
collections in both directions. It includes staged edits, merges matching names
by MD5, and preserves Unicode names, empty collections, unresolved hashes and
other destination collections. Choose an existing copied Realm for stable →
lazer, or optionally merge an existing stable file for lazer → stable. Review
the new output path before starting. Copying and reopen verification run in the
background; the dialog cannot close during publication. The source, destination
input and editing session stay unchanged.

**Save** / Ctrl+S saves the opened database in its current folder. Close osu!
first. The tool stages and reopens the edited database, creates a unique dated
backup of the original next to it, verifies that backup, then atomically replaces
the opened file. The details panel shows the backup and save report paths.
Each save keeps a new backup; a clean session needs no write. A new stable file
asks for an unused filename. **Tools → Save a copy…** retains the separate export
workflow, leaving the opened source unchanged. The classic Tk interface also
retains its separate-export Save behavior.

Opening a Realm asks whether lazer is closed. Save checks for intervening source
changes and holds Realm's native lock-file protocol during publication; it refuses
an open Realm. Stable saves coordinate other Studio instances, but osu!stable
must be closed by the user. No forced unlock or schema migration is performed.
If saving fails before replacement, the source stays intact and staged edits
remain in the editor. Keep any backup/report named in the error. To recover, close
osu! and Studio, preserve the current file separately, then copy the dated backup
back to the original filename. Save/verification cannot be interrupted mid-publication.
Cancellation of reads/import requests discards results; an active file/network
read may need to finish first. Scans check cancellation between files.

## Platform audit and remaining blockers

| Area | Linux | Intended Windows x64 behavior / limitation |
| --- | --- | --- |
| Qt 6.12 Widgets | Tested locally on Arch/KDE Wayland | User's VM opened the UI and now reports a successful packaged self-test. Target Windows 11 x64 and Windows 10 1809+ x64; exact VM OS/build and manual DPI acceptance remain unrecorded. No x86/ARM64 package in this milestone. |
| Python paths/processes | pathlib and argument lists | Spaces/Unicode use UTF-8 JSON and subprocess output. No shell command construction. Long-path edge cases still need Windows testing. |
| Settings/logs/cache | Qt standard directories; Linux XDG | QSettings uses platform storage; QStandardPaths selects cache and local app-data logs. Logs omit import-link values and exception payloads. Classic scanner now chooses LOCALAPPDATA on Windows. |
| Stable .db | Existing strict reader/writer; Save backs up and updates the opened file | Pure Python. Staging/new outputs use hard links in the same parent filesystem; **NTFS recommended**. FAT/exFAT/network-share hard-link support is not assumed. Failure before publication leaves the source intact. |
| Realm | Existing .NET 8 / Realm 20.1.0 helper | The actual NuGet package includes win-x64/realm-wrappers.dll. Its PE imports are KERNEL32 and bcrypt. Publish self-contained to avoid requiring .NET on the friend's PC. Database/schema compatibility still depends on the supplied lazer version. |
| File locking | Source hashes, exclusive Realm `.lock` lifetime lock, verified dated backups and atomic replacement; tested against the actual SDK | Windows uses Realm Core's byte-zero `LockFileEx` protocol. Native inspection edits a temporary copy. Windows locking/replacement still needs VM testing; do not open a live/locked Realm. Stable's separate lock coordinates Studio only. Windows ACL inheritance applies; Unix 0600/0700 is not a Windows ACL guarantee. |
| Downloader | ZIP/CRC/MD5 validation on first download; persisted verification reused for unchanged archives | No external download/extraction program. Windows file signatures also query native change time. Frozen smoke covers validation/resume; Windows timestamps, live mirrors and TLS need the Windows acceptance run. |
| Build | Local Linux frozen smoke passed | Windows build and mandatory frozen self-test passed according to the user's VM report. This recipe runs PyInstaller on the target OS. Wine remains unconfigured/unverified; a clean Windows runtime/DPI check is still required. |

Qt 6 uses device-independent coordinates. The main screen and both dialogs are
tested at default and compact sizes and with explicit scale factors; Windows mixed-DPI monitor
movement, Windows file locking, Defender/SmartScreen and an unsigned build remain
unverified. Portable builds include the one-click updater described in
[the feature guide](../docs/collection-studio.md#application-updates). No installer
or code signing is added. Tagged release
uploads are handled separately by the GitHub workflow described below.

## Reproducible local one-folder build

Build prerequisites only: **CPython 3.12.14 x64**, **uv 0.12.19**, **.NET SDK
10.0.112**, internet for locked package restore and license texts. The friend
receives the complete `CollectionsStudio` folder, including `_internal`, and
does not install Python, Qt or .NET. Do not send only the executable.

Run on Windows for a Windows build, or Linux for the Linux proof build:

```sh
uv sync --frozen --extra desktop --extra desktop-build --python 3.12.14
uv run --frozen --extra desktop --extra desktop-build python desktop/build_desktop.py
```

The recipe checks the interpreter and SDK, copies the unmodified helper source
into an isolated build folder, restores the checked-in RID lock, pins .NET runtime
8.0.31, publishes the helper self-contained without trimming, collects licenses,
and builds PyInstaller 6.22.3 with PySide6 Essentials 6.12.0. Corresponding tagged
Qt/PySide source archives are retained beside the build with SHA-256 records;
their license/attribution trees supplement missing wheel license files. No website modules or
Tk widgets are bundled. The output is one folder with replaceable Qt libraries.
An existing output folder is rejected; use `--output "new build folder"` for a
later build. Input versions/dependencies are reproducible; byte-for-byte identical
binaries are not claimed (toolchain timestamps/platform outputs can vary).

The default `--profile debug` preserves this original packaging. Release CI passes
`--profile release`: Linux strips native symbols and excludes the unused GTK theme
plugin before collecting its dependencies, retaining X11/Wayland/portal/image
support. Windows keeps its existing packaging. Both profiles retain the bundled,
untrimmed .NET runtime and all notices/sources. See [release profile details](../docs/releases.md#release-and-debug-packaging-profiles).

Output: `artifacts/desktop-build/dist/CollectionsStudio/`. The builder runs its
frozen executable's disposable `--self-test --report FILE` with Python/.NET tools
absent from PATH, writes `packaged-self-test.json`, and records all bundle file
hashes in `bundle-sha256.json`. This does not substitute for a clean Windows VM.
Maintainers can prepare a missing RID lock once using `--rid win-x64 --prepare-lock`
with a new `--output`; review it before use. Do not silently regenerate locks in
a release build.

NuGet metadata is copied as `nuget/<package ID>/package.nuspec`, with the
package identity and notice paths in `dependency-manifest.json`. This avoids
repeating long IDs in bundled paths, without dropping any license/attribution
files. If an older source ZIP fails during PyInstaller COLLECT at a long
`_internal\notices\nuget\….nuspec` destination, replace `collect_notices.py`
with the updated version and use a new output folder. The old recipe can also
be retried with a short, unused local path such as `--output C:\csbuild1`.
Very deeply nested source/output paths still need Windows long-path support or
a shorter build location; the normal `C:\Projects\CollectionsStudio-source`
layout is covered by the packaging regression check.

An older packaged self-test can report a missing temporary `source collection.db`
after Save, with Japanese folder characters shown as garbled text. Its save report
was decoded using the Windows locale rather than UTF-8. The updated
`tools/qt_package_smoke.py` reads the report explicitly as UTF-8. Replace that
source file and rebuild into a new output folder; the already built executable
contains the old self-test. No Windows locale change is required.

An assertion immediately after reopening that saved fixture can also be caused
by comparing path strings literally. The app canonicalizes the opened path, so
Windows aliases/casing can change its spelling. The updated self-test uses
`Path.samefile` to verify that the report identifies the opened file, and retains
the content and exact-backup checks. Other self-test checks report descriptive
errors; a failing native helper also includes its captured diagnostic output.

If the SDK check reports `dotnet.exe was not found on PATH` (or an older build
shows `FileNotFoundError: [WinError 2]`), install the x64 .NET **SDK 10.0.112**,
then close and reopen PowerShell. Verify with `dotnet --list-sdks`; installing only
a runtime is insufficient. For a default installation already present at
`C:\Program Files\dotnet\dotnet.exe`, refresh the current session with
`$env:Path = "C:\Program Files\dotnet;$env:Path"`. This failure happens before
the build output folder is created, so retry the same build command afterwards.

## Windows acceptance run — still required

Use a clean Windows VM without Python, uv, the SDK or .NET installed. Copy the
whole build folder to a path with spaces and Unicode, then:

```powershell
.\CollectionsStudio.exe --self-test --report "$env:TEMP\studio-frozen-check.json"
Get-Content "$env:TEMP\studio-frozen-check.json"
.\CollectionsStudio.exe
```

The self-test uses disposable stable fixtures, same-path saves with exact backups,
offline MD5-verified ZIP downloads and unchanged-archive resume without ZIP reads,
the Qt download/restore dialog, a detached Qt migration fixture, Unicode names/paths,
and the native helper's 59 Realm assertions. Then
manually open supplied **disposable** stable and lazer copies, edit/import/undo,
save twice and reopen, and compare each backup to the previous file. Also test
**Save a copy…** and compare the source's hash. Verify a locked source
fails safely, an existing new-file destination is refused, cancelled scans/imports do not
change views, and unresolved hashes remain after save. Test a real missing-map
download in the Qt dialog, cancel and reopen its queue. Confirm completed rows
appear immediately, then change/delete an archive and confirm it is revalidated.
Migrate both ways
through the Qt dialog using disposable database copies. Check 100%,
125%, 150% and 200% scaling, keyboard selection, resizing and moving between
monitors. Record OS/build, architecture, screenshots and results. Only after this
run can Windows support be labelled verified.

The owner selected MIT for first-party code. The build copies LICENSE, CREDITS.md
and THIRD_PARTY_NOTICES.md to the distribution and its bundled notices directory.
The Qt Tools menu and classic Help menu expose the documents in Credits and licences.
Before distributing publicly, complete [the dependency/source/notice review](THIRD_PARTY_NOTICES.md).
For single-file Windows/Linux binaries and tagged GitHub Releases, follow
[the release instructions](../docs/releases.md).


## Single-executable builds and GitHub releases

The default local recipe above still creates a portable folder. Add `--onefile`
to `desktop/build_desktop.py` for one Windows EXE or one Linux ELF executable;
the complete runtime/helper/notices are embedded and unpacked at startup. The
GitHub release workflow selects this mode on each native runner and attaches
checksums and one combined sources-and-notices ZIP. See [release instructions](../docs/releases.md)
for tag/manual triggers, Linux requirements and rebuilding with modified libraries.
