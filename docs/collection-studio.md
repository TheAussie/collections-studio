# Collections Studio

A desktop GUI for managing osu!stable `collection.db` files and collections in a
osu!lazer `client.realm`. Use disposable copies while testing. Import public osu!collector collections and
copy collections between the two formats. Download missing beatmap archives
with mirror fallback. It runs independently
of the web app, without OAuth credentials or a web server.

## Launch

The Qt Widgets interface, including downloads/resume and format migration:

```sh
uv run --frozen --extra desktop python -m tools.qt_collection_studio
```

Add `--file /path/to/collection.db` to open a stable file immediately. Close osu!
before opening a database; opening a Realm asks whether lazer is closed. The
Qt interface uses virtual tables without paging. Use **Tools → Get missing maps…**
or **Tools → Migrate collections…** for the dialogs described below. Completed
archives appear as **Downloaded**; import them through osu! and refresh inventory
before they become **Available**. Paths, exact hashes and reports appear in details.
The download dialog can close after cancellation finishes; migration waits for
copying and reopen verification. Both use the existing engines and file protections.

See [Qt setup and portable builds](../desktop/README.md) for dependencies,
Windows limitations and the remaining Windows acceptance checks. The user reports
a successful Windows build and packaged self-test; manual acceptance is still
pending. The original interface remains runnable independently.

For the original Tkinter interface, from this repository:

```sh
./tools/collections-studio
```

To open a stable file directly, use **Open collections…** or:

```sh
./tools/collections-studio --file /path/to/collection.db
```

Classic interface requirements: Python 3.12+ with Tk. Realm operations additionally need a .NET SDK
that can build `net8.0` and the .NET 8 runtime. Stable editing, website imports,
inventory reads, and downloads use only Python's standard library. The first
Realm operation builds the native backend using
the checked-in NuGet lock file. Install the documented prerequisites first.
No third-party Python packages, Python Realm binding, or full osu! source build
is needed. The launcher prefers system Python so the desktop Tk font renderer
can display Unicode collection names. Set `COLLECTIONS_STUDIO_PYTHON` to select
another Python installation if needed. `uv` is used for repository tests only.
The window starts at up to 1360×900, adapts to smaller screens, and supports
resizing down to 1000×700. The map viewport shrinks to keep action buttons
visible; narrower tables have a horizontal scrollbar.

The backend pins Realm SDK **20.1.0**, matching the installed osu!lazer AppImage
**2026.1005.0-lazer**, checked from its bundled dependency manifest. Compatibility
with other Realm formats/builds is not established; unsupported collection schemas
are rejected without migration.

## Application updates

Portable Windows/Linux x64 builds check the latest stable GitHub release in the
background on startup. An update button appears when a newer version is available.
**Tools → Check for updates…** opens the same dialog at any time, with release notes
and an option to turn off startup checks. Preview/beta releases are not installed
automatically, and a newer installed version is never downgraded.

Choose **Download and restart**. Unsaved collections offer Save / Discard / Cancel;
a cancelled or failed save stops the update. The client stays open while the
download is checked against that release's SHA256SUMS and, when supplied, GitHub's
asset digest. Cancellation removes the partial download. After verification, a
temporary copy of the executable waits for the old client to exit, replaces it,
and reopens the current database. Settings and saved song-library associations
remain in their existing locations. No updater service, separate server, external
Python installation or installer is involved.

Concurrent updates to the same executable are coordinated by Studio's OS-backed
file lease. Other client instances are never forcibly closed.

The previous executable is retained until the new GUI confirms startup, then the
temporary helper/download/backup are removed. A launch failure or early exit
restores the previous executable and reopens it. A client that is still starting
after the confirmation timeout is left running with its backup retained. The app
folder must be writable; use a folder you own. Source checkouts and one-folder
debug bundles keep their normal manual update process.

Install the first updater-enabled release manually once: older releases do not
contain this updater. Update checks are anonymous HTTPS requests to the project's
GitHub repository. Checksums verify download integrity; releases retain the same
publisher/repository trust as manual downloads.

## Manage collections

1. Close lazer before making a fresh copy of `client.realm`.
2. Choose **Open collections…** and select a Realm copy or stable `collection.db`.
   **New collection.db** starts a blank stable file without needing a Realm.
3. Select a collection on the left. Search by collection name, or search its maps
   by artist, title, difficulty, mode, or MD5. Searches cover the whole selected
   collection. The classic interface shows 500 maps per page; Qt has a virtual table
   covering the whole collection.
4. Use **New**, **Rename**, or **Delete** to manage collections. Delete asks for
   confirmation and removes collection membership, keeping beatmap data intact.
5. Select maps with Ctrl/Shift clicks. **Select all shown** or Ctrl+A selects the
   current page in the classic interface, or all filtered rows in Qt.
   **Remove selected maps** removes those memberships from the
   selected collection, leaving other collections and beatmap data intact.
6. **Import .db…** adds its contents to the working session. Exact
   same-name collections merge; duplicate MD5s are skipped case-insensitively.
   Names retain case, Unicode, and whitespace. Empty collections remain present.
   If existing duplicate names make a merge ambiguous, rename or delete the
   duplicates first. An ambiguous import applies no partial changes.
7. **Undo** or Ctrl+Z reverses a staged operation, including a whole import.
8. In Qt, **Save** or Ctrl+S creates a dated backup beside the opened database,
   then saves the verified changes to that same path. For example,
   `client.backup-20261026-….realm` retains the previous `client.realm` exactly.
   A second save creates another backup; earlier backups remain intact.
   New stable files ask for an unused filename. Stable saves retain the original
   file's version marker. The details panel shows the saved file, backup and report.
   **Tools → Save a copy…** instead creates a separate
   `collections-export-YYYYmmdd-HHMMSS/` directory with `client.realm` or
   `collection.db`, plus `import-report.json`.

The classic Tk interface retains **Save new Realm…** / **Save new .db…** with a
chosen parent folder and a new export directory; its source is left unchanged.
Existing separate exports are never overwritten.

Edits remain in memory until Save. Qt keeps the opened path as its source after
saving and clears the saved undo history. Closing or opening another file asks
before discarding unsaved changes. Long database operations run in the background.

Map labels come from the supplied Realm, stable inventory, and imported metadata. Unknown
hashes show an explicit fallback and their MD5 when selected. A `collection.db`
contains names and difficulty hashes, so importing it does not install missing
beatmaps, audio, or backgrounds. Use the separate download queue for those files.

### Copy, move and browse songs in Qt

Select one or more maps, then choose **Copy to…** or **Move to…**. Pick a destination
collection and review the counts of new additions and maps already there. Copy
keeps the source memberships; Move ensures the destination contains each selected
MD5 and then removes it only from the source collection. Cancel leaves the session
unchanged. One Undo reverses the whole operation, and Save applies it to the file.
Create another collection with **+ New** first if no destination exists.

For an empty or existing collection, choose **Browse songs**. The target name stays
in the heading. Realm supplies all its indexed beatmaps, including those outside
any collection. For stable files, load `osu!.db` or scan Songs with the buttons
shown in the empty library, or use the Tools menu. A neighboring `osu!.db` is read
automatically when opening `collection.db`. Scans and filtering run in the background.

The browser initially shows **Available** maps and hides hashes already in the
target collection. Search, select with Ctrl/Shift or **Select all**, and choose
**Add selected to collection**. Turn off **Not already in this collection** to see
the membership column; change the availability filter to inspect other indexed
Realm entries. **Back to collection** returns to its memberships. Remote import
labels and downloaded archives alone do not populate the installed song library.

Copy, Move and Add identify duplicates by MD5 without regard to letter case.
Repeated selections or additions introduce no duplicates. A move to a destination
that already contains a map still removes the selected source membership. Existing
legacy duplicates elsewhere are preserved, and different revisions with different
MD5s remain distinct. Song files, metadata and other collection memberships stay
in place. Collection names that already repeat in an opened file are distinguished
by collection number in the destination picker.

## Migrate between stable and lazer

Open the source file and choose **Tools → Migrate collections…** in Qt or
**Migrate…** in the classic interface. The direction follows the open file:

| Source | Destination |
| --- | --- |
| `client.realm` | A new `collection.db`, optionally merged with an existing stable file |
| `collection.db` | A new Realm based on an existing copied `client.realm` you select |

1. All collections are selected initially. Use **Current collection**, Ctrl/Shift
   selection, **Select all**, or **Clear selection** to choose which to copy.
   The migration includes the current session's unsaved edits.
2. For stable → lazer, browse to a copied destination Realm. It must be a valid
   database created by lazer; the tool preserves its schema and other data.
   For lazer → stable, optionally enable **Merge with an existing collection.db**
   and select that file. Otherwise, a fresh stable file is created.
3. Choose an output parent folder, review the displayed new file path, and click
   **Migrate to collection.db** or **Migrate to client.realm**.

The result appears in a new `collections-migration-YYYYmmdd-HHMMSS-…/` folder,
with `import-report.json` and `migration-report.json`. The tool reopens and checks
the result before publishing it. It rejects inputs that changed during the
operation and never overwrites an existing output directory. Your source file,
destination input, staged edits, and undo history stay unchanged.

Exact matching collection names merge by case-insensitive MD5; repeated incoming
memberships are skipped. Names preserve Unicode, case, and whitespace, and empty
collections are copied. Other destination collections remain present. Duplicate
names in the incoming selection combine into one collection; multiple existing
destination collections with a matching name are ambiguous and stop the migration.
When merging an existing stable file, its version marker is preserved.

This copies collection names and memberships. Realm IDs and timestamps have no
equivalent in `collection.db`. Beatmap files, scores, settings, audio, and images
are not transferred; use **Get missing maps…** for missing beatmap archives.

## Stable inventory: osu!.db and Replay Parser

When opening `collection.db`, the tool automatically reads a neighboring
`osu!.db` (or `osu.db`) if present. **Read osu!.db…** selects a database elsewhere.
It reads cached MD5s, titles, artists, difficulties, modes, and IDs without opening
or rehashing individual beatmap files. It ignores account details. The reader
handles the 2025 change from double to float star-rating pairs and validates the
complete record layout before updating the displayed library.

`osu!.db` is the client's cache of installed maps. If it is stale, use
**Scan Songs folder…** to refresh from actual `.osu` bytes. This fallback uses
the same path + file size + nanosecond modification time strategy as your
Replay Parser's `src/beatmap_index.rs`: unchanged files reuse their MD5s, changed
files are rehashed, and removed entries disappear from the tool's cache. The
cache is private under `$XDG_CACHE_HOME/collections-studio` or
`~/.cache/collections-studio`; Songs files are read-only.

**Replay cache…** also accepts Replay Parser's existing
`beatmap-index-cache.json`. It checks each file's current size and modification
time, reuses only matching entries, and skips stale/missing paths. It never
modifies the Replay Parser cache or project. Cache-only labels fall back to
the `.osu` filename; `osu!.db` supplies fuller metadata more quickly.

Lazer inventory continues to come from its Realm. Soft-deleted sets and detached
metadata do not count as installed maps. Downloaded files are marked separately
and do not become installed merely because remote metadata is available.

### Reuse the library after reopening

Qt remembers the selected Songs scan or osu!.db inventory for each `collection.db`.
Opening that collection file again, including after restarting Studio, restores
the saved JSON library in the background. Saving a new collection.db or using
Save a copy carries its library association to the new path. The association is
stored in local app settings, leaving the collection.db format unchanged.

Songs scans reuse the existing JSON file. Reopening checks cached file sizes and
timestamps, preserves map labels and skips changed/missing files without walking
the whole Songs directory or rehashing maps. Scan Songs again to find newly added
or changed beatmaps. Identical scan entries leave the JSON's bytes and timestamp
unchanged, including when the existing cache is newer.

Reading osu!.db explicitly, or loading one next to collection.db automatically,
saves its parsed beatmap metadata in `osu-inventory-<source-hash>.json` in the app
cache directory. Repeated identical reads reuse that file without rewriting it.
Future opens read the JSON rather than reparsing osu!.db; the snapshot remains
usable if the original osu!.db is unavailable. If that database's size/timestamp
changes, Studio shows a refresh notice. Read osu!.db again to update the snapshot.
Player/account data is not included in the cached inventory.

Missing or damaged caches do not prevent opening collections: Studio reports the
problem and uses a neighbouring osu!.db when available. Cached data never changes
collection memberships or makes the editing session dirty. Previously created
scans need one selection through Scan Songs to associate them with a database;
unchanged entries are reused immediately. Realm files continue to use their own
embedded beatmap library.

## Import from Maps or osu!collector

For your Maps website, open **Manage collections**, choose **Import link or
collection.db →**, review the contents, then **Create import link**. In the
manager, open a file or choose **New collection.db**, select **Import link…**,
and paste the link. All included collections merge into the working session.
Map labels are carried over; MD5 duplicates are skipped, and the import is
undoable. Your existing unrelated collections stay present. Save when ready.

Maps links are revocable snapshots. Website edits do not change an old link;
create a new one for updated contents. Anyone with the link can read its selected
names, MD5s, and map labels. Notes stay private. See the
[API and sharing guide](collection-api.md) for revocation and file downloads.

Open a source file or choose **New collection.db**, then select
**Import link…**. Paste a public osu!collector collection URL such as
`https://osucollector.com/collections/44/speed-practice`, or the numeric ID `44`.
The collection merges into the current stable or Realm workspace. Duplicate MD5s
are skipped within each exact same-name collection, and the operation is undoable.

The importer reads the site's public JSON endpoints. Original collection hashes,
including valid unknown hashes, remain authoritative: newer metadata never
replaces an older stored MD5. Invalid/incomplete membership responses abort the
import. If optional map-label metadata is unavailable, complete memberships are
still retained and the status explains the missing labels. URL query filters
do not change the imported collection; the entire public collection is imported.

## Download missing maps

Choose **Get missing maps…** after importing. The queue defaults to **Last import**
and can also check the selected collection or all collections. MD5s are deduplicated
across that selection. For stable, load `osu!.db` or a Songs/cache inventory first
so installed maps are skipped.

The default mirror order is **osu.direct → Mirria → Nerinyan → Sayobot → Nekoha →
Beatconnect → osu!dl → Hinamizawa**. The checkboxes appear in two rows, read left
to right and then top to bottom. Disable a mirror before starting if needed.
osu.direct, Mirria, and Hinamizawa support exact MD5 lookup; the other providers
supply archive downloads once a set ID is resolved. At least one lookup provider
must remain enabled. A failed lookup tries the next enabled lookup provider; a
failed, corrupt, or wrong-revision archive tries the next enabled download mirror.
Requests are sequential, spaced by at least a second per mirror, with timeout
bounds, outage cooldowns, and `Retry-After` handling.

Hinamizawa is last because it also cascades across upstream mirrors. Its streaming
archive endpoint is used rather than its default JSON handoff. osu!dl's anonymous
endpoint follows HTTPS redirects to signed R2 downloads; its coverage is limited
to ranked, approved, and loved maps. Beatconnect uses anonymous downloads. A
CAPTCHA, login page, JSON error, or rate limit causes fallback to another enabled
provider. More archive sources cannot recover an old or locally edited hash
unless a provider can resolve it and an archive contains those exact `.osu` bytes.

Choose a save folder, then **Download missing** or select rows and choose
**Download selected**. The queue shows map identity, status, mirror, byte progress,
and individual result details. **Cancel** keeps completed archives and the saved
queue, removing only the partial archive in progress. A network read can take up
to 15 seconds to cancel. Use **Resume remaining** in the same window to continue;
**Resume remaining** continues only cancelled/interrupted and not-yet-started
entries. Failed entries stay failed until **Retry failed** (or an explicit
**Download selected**) is chosen. The downloaded, installed, remaining and failed
counts use the same definitions while running and after cancelling. An unfinished
cancelled entry remains in the remaining count; failed attempts are listed separately.

To continue after closing the manager, open a collection file (or create an empty
one), choose **Get missing maps… → Resume queue…**, and select the original download
folder. The **Saved download queue** scope restores all requested hashes and the
last enabled mirrors. Completed rows immediately show **Already downloaded**, with
their beatmap labels and a count of what remains. Click **Resume remaining**.
Maps already installed according to the loaded inventory are skipped. If osu! has
consumed an archive saved directly into Songs, matching set folders are checked
in the background for the exact requested `.osu` MD5s. Matches show **Already
installed**, require no mirror request and are cached by file identity/timestamps.
A matching folder name alone never proves completion. Previously
verified archives with unchanged file identity, size and timestamps reuse their
saved metadata; their ZIP contents are not reopened or rehashed, and no mirror
request is made for them. Changed or missing archives return to the remaining work;
changed files are reverified, and missing/corrupt files are downloaded again
without overwriting existing files. Older download indexes need one verification
pass to create these records; later resumes skip unchanged archives.
The interrupted archive starts again from the beginning; partial-byte HTTP resume
is not used.

Keep `.collections-download-queue.json`, `.collections-downloads.json`, and the
`.osz` files together in that folder. The queue is saved atomically before the first
network request, including every not-yet-started hash. Later batches in the same
folder add to its queue, so the saved scope may span several collections or imports.
The queue stores hashes and mirror names. The version-2 index stores each verified
archive's file identity/timestamps and exact map metadata. Loading it checks those
file attributes; it also retains exact installed-file records and failed/cancelled
outcomes independently of per-run reports. Existing reports in an older download
folder are read once to recover failure history across runs; a new report never
discards an older run's untouched entries. No existing reports are moved or deleted.

New per-run reports retain attempt details in the app-data `CollectionsStudio/download-reports`
folder (`~/.local/share` / `XDG_DATA_HOME` on Linux, `%LOCALAPPDATA%` on Windows).
Only the newest 10 reports there are retained automatically. Cleanup never touches
Songs folders, `.osz` files or the saved queue/index. Reports are diagnostics;
resume uses the durable queue/index rather than requiring one report filename.
For archives downloaded before saved queues were introduced,
reopen the source collection, use **Browse…** to select the old folder, and start
**Download missing**; the existing download index still allows verified reuse.

Downloads use private temporary `.part` files. ZIP integrity/CRC, filenames,
expanded sizes, `.osu` headers, the set ID when present, and the exact original
`.osu` MD5 are checked before a file is published. Limits are 512 MiB per archive,
2 GiB expanded, 20,000 entries, and 32 MiB per `.osu` file. If mirrors only have a
different revision, the item remains failed; collection hashes are not changed.
Several requested difficulties from one set reuse the same verified `.osz`.
Existing archives are never overwritten. New, changed or legacy archives undergo
full verification; unchanged archives reuse their verified record. A private download queue,
download index, and per-run JSON report retain requests, verified file locations,
and mirror failure details.

**Ready/Downloaded means the archive is verified, ready for import into the game.**
Import the `.osz` files through your osu! client's normal file import. This tool
does not inject beatmap/audio/file records into a Realm or extract into Songs.
Refresh the inventory afterwards. Deleting a collection or membership keeps
downloaded archives and existing cached backgrounds intact.

Endpoint and format references checked during development:
[osu.direct API](https://osu.direct/api/docs),
[Mirria API](https://mirror.lisek.cc/docs),
[Nerinyan routes](https://github.com/Nerinyan/nerinyan-api-v2/blob/master/main.go),
[Sayobot API documentation](https://www.showdoc.com.cn/SoulDee),
[Nekoha frontend](https://mirror.nekoha.moe/assets/index.js),
[Beatconnect](https://beatconnect.io/),
[osu!dl anonymous download route](https://github.com/kaysting/osudl/blob/main/apps/web/routes/direct.js),
[Hinamizawa MD5 lookup](https://mirror.hinamizawa.ai/docs/beatmap-info),
[Hinamizawa downloads](https://mirror.hinamizawa.ai/docs/beatmap-download),
[osu!collector](https://osucollector.com/), and
[ppy legacy database format](https://github.com/ppy/osu/wiki/Legacy-database-file-structure).

## Data preservation and reports

During staging, the source Realm is read as an ordinary read-only file. Realm itself opens only
a private temporary copy. The tool checks source SHA-256 before/after, rejects
stale edit sessions, and performs one transaction against the temporary copy.
It verifies exact collection contents and timestamps, schema identity, and a
logical SHA-256 audit of every other top-level table, including owned embedded
data. It reopens the result and repeats verification before publishing it.
An audit mismatch prevents publication. Qt **Save** holds Realm Core's exclusive
lock-file protocol, verifies an exact dated backup, then atomically replaces the
opened file. An active Realm SDK connection refuses this lock. Stable's separate
lock coordinates Studio instances only, so stable must also be closed before Save.
No lock file is deleted or forcibly unlocked. Source changes, backup failures or
replacement errors leave the editor's changes pending. Before replacement, any
failure leaves the source intact. **Save a copy…**, classic exports and migrations
always leave their input files unchanged.

Each same-path save writes a sibling `*.save-report-….json`, recording the backup,
output hashes and save state. A report marked `prepared` alone does not confirm
publication. If the final report/folder sync fails after replacement, the UI reports
the successful save with a warning instead of leaving it falsely unsaved. Keep
the backup and check the saved file. For recovery, close osu! and Studio, preserve
the current file separately, then copy the dated backup to the original filename.

The report records source/output hashes, collection changes, per-table record
counts and audit hashes, and the reopen result. Temporary files and outputs are
private to the current user on Linux. Legacy inputs and edit plans are limited
to 32 MiB, 10,000 collections, and 1,000,000 total memberships.

## Developer checks

```sh
uv run --frozen --extra desktop pytest -q
uv run --frozen --extra desktop ruff check scripts tests tools desktop
uv run --frozen --extra desktop ruff format --check scripts tests tools desktop
dotnet build tools/RealmCollectionImport -c Release -p:RestoreLockedMode=true
dotnet run --project tools/RealmCollectionImport -c Release --no-build -- self-test
```

The Python suite exercises staged edits and GUI controls without changing a real
Realm. GUI tests need a display; classic tests skip when Tk cannot connect to one,
and Qt tests require the desktop extra. Native
self-tests create temporary Realms and cover strict binary parsing, union/merge,
idempotence, Unicode, empty collections, rename/delete/member edits, stale input,
schema-version preservation, and unrelated-data audit failures.

For automation, the native backend also exposes `inspect`, `read-collections`,
`preview`, `merge`, and `edit`; run it with `--help` for arguments.


## Credits and licences

Open **Tools → Credits and licences…** in Qt or **Help → Credits and licences…**
in the classic interface. Read the dependency/service/format acknowledgements,
first-party MIT licence and third-party notice summary without opening a collection.
The same files are available in the source and portable distribution.
