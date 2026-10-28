# Collections Studio

A desktop editor for osu!stable `collection.db` and osu!lazer `client.realm`
collections. Manage names and memberships, import collection snapshots or public
osu!collector collections, migrate between formats, and download missing maps
with resumable queues and MD5 verification. Qt and the classic Tk interface use
the same engines. No web server, OAuth credentials or Flask packages are needed.

## Download

Get the [latest release](https://github.com/TheAussie/collections-studio/releases/latest).
Windows x64 uses `CollectionsStudio-windows-x64.exe`, with no installer. Linux x64
uses `CollectionsStudio-linux-x64`; make it executable with `chmod +x` and run it.
Python and .NET are bundled. Linux requires glibc 2.35+ and desktop system libraries;
see [platform requirements and release assets](docs/releases.md). Releases also
include checksums and one combined archive of matching sources and third-party notices.

Portable builds check for newer stable GitHub releases in the background. Use
**Tools → Check for updates… → Download and restart** to verify the download,
close the client, replace its executable and reopen the current database.
Unsaved edits offer Save / Discard / Cancel. The updater runs from the app itself;
no service, installer or separately installed runtime is required.

## Run from source

Use Python 3.12+ and uv. The Qt interface:

```sh
uv sync --frozen --extra desktop
uv run --frozen --extra desktop python -m tools.qt_collection_studio
```

The classic interface uses Python's Tk installation: `python -m tools.collection_studio`
or `./tools/collections-studio` on Linux. Realm operations additionally require
the SDK/runtime documented in [desktop setup](desktop/README.md); stable-file
editing and downloading use the standard library. Close osu! before accessing
game databases and use disposable copies for testing. Save creates a verified
backup before updating an opened file; Save a copy and migration create new files.

See the [feature guide](docs/collection-studio.md),
[collection-link protocol](docs/collection-api.md), and
[portable build instructions](desktop/README.md).

In Qt, select beatmaps and use **Copy to…** or **Move to…** to choose another
collection. **Browse songs** lets you fill a collection from the game's inventory:
Realm supplies it directly; stable files use **Read osu!.db…** or
**Scan Songs folder…**. Existing destination MD5s are skipped case-insensitively.
Changes support Undo and stay in memory until Save.

## Checks and builds

```sh
uv run --frozen --extra desktop pytest -q --tb=short
uv run --frozen ruff check tools desktop scripts tests
uv run --frozen ruff format --check tools desktop scripts tests
dotnet build tools/RealmCollectionImport -c Release -p:RestoreLockedMode=true
dotnet run --project tools/RealmCollectionImport -c Release --no-build -- self-test
```

Qt can use `QT_QPA_PLATFORM=offscreen` for headless tests. Classic Tk tests skip
when a display is unavailable. Tests and native self-tests use synthetic files;
GUI audit scripts require explicitly supplied disposable fixtures. Contract JSON
and binary hex fixtures are kept in `tests/fixtures/` and match the web producer.

The build recipe pins its interpreter, SDK, runtime, NuGet dependencies, Qt
sources and PyInstaller version. Build separately on each target OS. Linux checks
do not establish Windows acceptance; manual clean-Windows acceptance is pending.

## License and distribution

Collections Studio's first-party code uses the [MIT licence](LICENSE). You may
copy, modify, redistribute and use it commercially while retaining its copyright
and licence notice. Third-party components keep their original terms.

Read [credits and acknowledgements](CREDITS.md) in the repository or open
**Tools → Credits and licences…** in Qt / **Help → Credits and licences…** in the
classic interface. The viewer contains credits, the MIT text and third-party
notices; portable builds include the same documents.

Preserve and review [third-party notices](desktop/THIRD_PARTY_NOTICES.md), matching
corresponding sources and the final bundle inventory before redistribution.


## Automated releases

The [release workflow](.github/workflows/release.yml) builds one portable Windows
EXE and one Linux executable. There is no installer or AppImage. A manual workflow
run produces artifacts; pushing a `v*` tag builds, self-tests and publishes a
release after both platforms succeed. Matching source, third-party notices and
checksums accompany the executables. See [release and rebuilding instructions](docs/releases.md).
