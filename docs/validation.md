# Local extraction validation

Verified on Linux with Python 3.12.14 and .NET SDK 10.0.112:

- 205 desktop Python tests passed, with no skips; Qt used its offscreen platform
  and the classic Tk tests used an available display. Settings were isolated.
- Locked offline NuGet restore and Release build passed with zero warnings/errors.
- The native helper passed all 59 synthetic Realm assertions.
- Frozen offline dependency checks and Ruff lint/format checks passed.
- The desktop environment contains no Flask, Requests, Gunicorn, Pillow or
  Playwright. Production desktop code has no web imports.
- Synthetic version-1 snapshot JSON and collection.db hex fixtures passed locally
  and matched the separate producer's bytes in an offline cross-project check.
- Existing desktop engines, interfaces, helper, packaging code, third-party
  notices and pinned build/source metadata were preserved byte-for-byte.

All dependency versions came from the existing local cache. No personal game
database, real share link, credentials or production service was used. The
portable bundle recipe was not rerun because its notice/source collection fetches
upstream material; final bundle/source/notice review remains required. Linux
checks do not establish Windows acceptance. The owner subsequently selected MIT
for first-party code; publication remains pending.


## Subsequent MIT licence and credits update

The owner requested permissive code reuse and acknowledgement of sources used.
First-party code now uses the MIT licence with TheAussie and contributors named
in LICENSE. CREDITS.md lists runtime/build dependencies, all locked native helper
packages, collection/mirror services, documented format/cache references and
development assistance. Third-party licences retain their original terms.

Qt exposes Tools → Credits and licences; the classic interface exposes Help →
Credits and licences. Both viewers show credits, the full MIT text and the notice
summary without opening game data. The builder retains these documents at the
bundle root and in bundled notices, recording their SHA-256 hashes. The frozen
self-test now requires the documents and the viewer to be present.

Verification: 213 desktop tests passed, with no skips; Ruff checks and the frozen
offline lock check passed. Tests cover source/bundle document lookup, missing
bundle documents, exact copied legal text and both GUI entry points. Both screens
were visually checked, including link/tab contrast. Existing portable binaries
were not rebuilt and Windows acceptance was not repeated. No dependency versions,
game databases, credentials, Git state or remote/publication settings changed.


## Windows/Linux release workflow and single-file build

Added `.github/workflows/release.yml`: native Windows x64 EXE and Linux x64 ELF
builds, manual artifact-only runs, and publication after successful builds on
`v*` tag pushes. Actions are pinned to verified upstream commits. Only the
publication job has contents write permission. No installer or AppImage is built.

Validation completed locally:

- 222 desktop tests passed, with no skips. New checks cover the executable native
  helper entry in the PyInstaller spec, one-file/folder layouts, notice/source
  asset contents, stable checksums and refusal to stage unverified binaries.
- Ruff lint/format and the frozen offline lock check passed.
- Workflow YAML, matrix/triggers/permissions, action input names and all Bash
  blocks were checked. GitHub Actions itself has not run locally.
- The actual Linux single-file builder passed, using cached, hash-verified
  upstream source archives/licence texts and offline NuGet restore. No new package
  versions were installed. The resulting 124,226,288-byte ELF ran the full frozen
  self-test with Python/.NET tools removed from PATH: credits/licences, Unicode
  saves/backups, downloads/resume, migration and all 59 native Realm assertions.
- The real release stager produced the executable, a notice ZIP with 379 entries,
  all four matching Qt/PySide/Shiboken source archives and verified SHA256SUMS.
  The extracted native helper retained executable permissions.

The local build ran on Arch Linux/glibc 2.44. Ubuntu 22.04 compatibility and the
Windows build will be checked on their native GitHub runners on the first run;
manual Windows acceptance remains separate. PyInstaller reported an unavailable
optional .NET tracing library (`liblttng-ust.so.0`); the native/frozen self-tests
passed without it. No Git repository, tag, remote, GitHub run or release was
created by this local work, and web/production/game data was unchanged.

## Public source preflight — 27 October 2026

- 222 desktop tests passed with no skips, using isolated temporary settings.
- Ruff lint and formatting checks passed for all 51 Python files.
- The frozen offline dependency lock check passed with existing cached tooling.
- All six pinned GitHub Action commits were verified against upstream repositories.
- The public source allowlist excludes environments, private data, generated
  executables, build outputs and caches. Unsafe credential-URL rejection fixtures
  were reviewed as synthetic test inputs.
- Native CI builds and release publication are the next verification stage;
  this local run does not establish manual Windows acceptance.

## First native CI run and Python setup correction

The first `v0.1.0` workflow completed the Linux native build successfully. Windows
stopped at actions/setup-python because its Windows catalogue lacks CPython
3.12.14. The release job was skipped, so that attempt published no release.

The corrected workflow keeps CPython 3.12.14 and uses uv's managed distributions
for both platform builds and the checksum job. The exact Windows x64 archive was
confirmed in the upstream python-build-standalone release. Project metadata is
0.1.1; the failed v0.1.0 tag is preserved. Native validation of this correction
runs on the new v0.1.1 tag before publication.

The next CI attempt identified that setup-uv's optional `python-arch` input needs
an uv feature newer than the pinned 0.12.19. Removing the input uses the x64
runner's native architecture and retains every runtime/dependency pin. The fix
is verified through a build-only workflow run on main before the next release
tag (v0.1.2); failed tags remain unchanged and no release was published by them.

## Self-hosted VM preparation and Windows test portability

The owner registered separate Windows Server 2022 x64 and Ubuntu 22.04.5 x64
runners for this repository. Both were verified online/idle with their intended
custom labels. The owner verified Xvfb after installing Ubuntu desktop libraries.
The failed v0.1.0/v0.1.1 tags were removed at the owner's request, with no release
published; project/lock metadata now starts again at 0.1.0.

The earlier Windows run reached tests: 215 passed, 3 skipped, and 4 failed on
platform assumptions. Three failures asserted Unix 0600 mode bits on Windows;
those assertions now run on POSIX while retaining the content/resume/export
checks on Windows. The fourth changed an mtime by one nanosecond, below NTFS
precision; it now uses a representable two-second change and verifies that the
mtime actually changed before checking stale-cache rejection. Runtime behavior
is unchanged. The next build-only run validates the corrected tests and native
packages on the new runners before any release tag is recreated.

Local verification after these changes: all 222 tests passed without skips;
Ruff lint/format, the frozen offline lock check, workflow YAML/label/permission
checks and Bash syntax checks passed. Native VM validation is performed by a
manual build-only workflow run; that event cannot execute the publication job.

The first self-hosted check reached tests on both VMs. Ubuntu passed 221 tests;
Windows passed 217 with the three documented platform skips. A cache-invalidation
fixture on both VMs rewrote an archive within the same filesystem clock tick;
it now waits for an observable change timestamp while explicitly retaining the
original size/mtime before asserting rejection. Windows also exposed the longer
NETWORK SERVICE temporary-profile prefix in the NuGet notice fixture. CI now
uses a short pytest base directory inside the dedicated runner's temp directory;
the full package-ID/notice-preservation and MAX_PATH assertions remain unchanged.

## Native build-only validation passed on the dedicated VMs

GitHub Actions run 40450736982 passed at commit
1b409ddc4acbdcedb3c772da295911021363e7aa. The Ubuntu 22.04.5 x64 runner passed
all 222 tests. The Windows Server 2022 x64 runner passed 219 tests and skipped
three fixtures: Windows symlink creation without developer mode, a POSIX-only
symlink fixture, and the native Windows lock acceptance fixture. Both platforms
then built their actual one-file executable, passed the mandatory frozen
self-test, staged the platform notices and matching sources, and uploaded their
release artifacts. This manual run published no release. Manual Windows UI/DPI,
clean-machine and game-database locking acceptance remain pending.

The owner-requested first release tag is v0.1.0. Its tag-triggered workflow repeats
native verification and publishes only after both platform jobs succeed.

## Collection copy/move and game library browser — 28 October 2026

Qt now exposes Copy to / Move to for selected memberships and Browse songs for
adding from the loaded game inventory. Workspace operations validate selections
before editing, deduplicate MD5s case-insensitively and use one Undo snapshot.
Existing legacy duplicate entries are preserved rather than silently cleaned up.
Library membership is separate from remote import metadata and downloaded archives.
No dependencies, native helper source or on-disk collection formats changed.

Local Linux verification with Python 3.12.14 / Qt 6.12.0:

- 225 tests passed; 16 classic Tk tests skipped because no display was available.
  New coverage includes duplicate/no-op transfers, moves into an existing target,
  stale selections, atomic failures, Undo, stable save/backups, Realm library
  membership, Songs scanning and a responsive 40,000-entry browser.
- The seven new Qt membership tests also passed with a 2× scale factor offscreen.
- The source-based offline UI smoke passed, including the new controls, existing
  download/resume/save/migration checks and all 59 native Realm assertions using
  the existing locally built helper. This was not a new frozen executable build.
- Ruff lint and formatting passed. Synthetic web collection-link / collection.db
  contracts remained compatible across the separate projects.
- Synthetic collection, library and destination-dialog screens were inspected at
  1360×900 and 960×640. The library keeps readable titles and horizontal scrolling
  when its extra columns exceed the viewport.

Tests used temporary synthetic files and isolated settings. No game database,
credential, production service, remote release or dependency installation was
used. These checks do not establish Windows UI or new packaged-binary acceptance.

## Smaller Linux release packaging — 28 October 2026

Release CI now selects `--profile release`. Linux strips native symbols and uses
a PyInstaller QtGui hook that excludes only the optional GTK theme plugin before
transitive dependency collection. The payload audit requires X11, Wayland and
offscreen platform plugins. The portal, image formats, Qt ICU, all application
features and all notice/source assets remain. Default / `--profile debug` retains
the previous packaging; Windows is unchanged in either profile. No dependency
versions or lock files changed.

Local verification used the existing pinned Python/.NET packages and cached,
hash-verified Qt source archives and notice texts. Both same-source one-file
builds passed the frozen self-test with Python/dotnet absent from PATH, including
all 59 native Realm assertions, save/backups, transfers/library browsing,
downloads/resume, migration and the licence viewer:

- Debug reference: 124,243,824 bytes (118.49 MiB), GTK theme still included.
- Optimized release: 96,991,320 bytes (92.50 MiB), GTK theme absent.
- Reduction: 27,252,504 bytes / 25.99 MiB / 21.9% on this Arch Linux build.
- 240 Python tests passed; 16 classic Tk tests skipped without a display. Build
  coverage checks default/debug/release and simulated Windows/Linux spec settings,
  GTK filtering, platform-plugin audit failures and notice/source preservation.
- Ruff lint/format, workflow YAML and Bash syntax checks passed.

An isolated `PublishTrimmed=true` locked restore stopped with NU1004 because it
adds Microsoft.NET.ILLink.Tasks 8.0.31, absent from the reviewed dependency lock.
Trimming remains disabled pending a deliberate dependency/Realm/JSON compatibility
change. The lock was not bypassed. All operations used synthetic temporary files;
no running user session or personal database was accessed. Native Ubuntu/Windows
runner validation and manual desktop acceptance remain separate; no run, tag or
release was published by this local work.

## Saved Songs and osu!.db inventories — 28 October 2026

Qt now remembers an inventory-cache association per canonical collection.db path.
Successful Songs scans reuse their existing JSON; explicit and neighbouring
osu!.db reads cache parsed beatmap metadata as JSON. Reopening a collection file,
including in a new application session, restores that library in a worker without
rehashing Songs or reparsing osu!.db. New-file Save and Save a copy preserve the
association; other databases do not inherit it accidentally. Realm inventory
continues to come from its own schema/data.

Identical inventory contents do not rewrite JSON or change its timestamp. Songs
cache comparison ignores directory enumeration order. Restored scans validate
file size/mtime, skip stale entries and retain labels. osu!.db snapshots remain
usable when the original database is unavailable and show a refresh notice if
its signature changes. Missing/corrupt caches preserve collection-file opening,
with a notice and neighbouring database fallback. Cache settings stay outside
game databases, and account/player data is not saved.

Local verification: 253 Python tests passed; 16 classic Tk tests skipped without
a display. New checks cover fresh-window restore, scan/explicit/automatic database
sources, unchanged newer caches, missing/changed files, corruption, cancellation,
empty inventories and Save/Save a copy. Ruff lint/format and the synthetic
web-to-desktop contract passed. The new optimized Linux executable passed its
frozen self-test with a clean profile and no Python/dotnet on PATH, including JSON
reuse/restore, existing UI operations and all 59 native Realm assertions. Only
temporary synthetic files/settings and existing cached build dependencies were
used. No user application session, personal database or production service was
touched. Native Windows validation and release publication remain pending.

## Built-in portable updates — 28 October 2026

Portable Qt clients check stable GitHub releases in the background and expose one
Download and restart action. The existing release executables and SHA256SUMS form
the update feed; no server/service or new dependency is added. Downloads enforce
repository/tag/platform URLs, HTTPS redirect hosts, byte limits and SHA-256 checks.
Unsaved changes offer Save / Discard / Cancel, with failed/cancelled saves stopping
the update. The old client stays open until the helper confirms readiness.

The same executable supplies a temporary helper mode, waits for parent exit,
holds Studio's OS-backed executable lease and atomically renames the old/new files.
The new GUI validates its version and executable hash before acknowledging startup.
Settings, inventory associations and the current database path are retained.
Successful handoffs remove helper/staging/backup files; failed launch or early exit
restores the previous executable. Slow but running new clients retain recovery
copies rather than being forcibly stopped. Source Python and one-folder bundles
are excluded from automatic replacement. Runtime staging/lease files are ignored
by Git.

Validation on Linux: 307 tests passed; 16 classic Tk tests skipped without a
display. Tests cover versions/platform selection, unsupported/missing/foreign
assets, checksum/size failures, cancellation, unsaved edits, failed saves, helper
readiness, concurrent updates, replacement/sharing failures, startup mismatch,
rollback, late startup confirmation and cleanup. Ruff lint/format, workflow YAML
and Bash syntax, the web/desktop contract and compact dialog visual review passed.

The optimized one-file Linux executable (about 92.55 MiB) passed the frozen
offline updater checks and all 59 Realm assertions. A real packaged rehearsal on
private copies then proved parent exit, physical executable replacement, new GUI
startup acknowledgement and helper cleanup, with an isolated config/cache/data
profile and no live HTTP/game data. Its report is bound to the tested executable
SHA-256 and version; new versioned releases cannot stage without this receipt.
The actual release stager also passed, preserving credits, notices and all matching
Qt/PySide/Shiboken sources. Only the rehearsal's image-verified private GUI process
was stopped; no existing user app or personal database was accessed.

Both native CI builds now require this rehearsal. Windows updater acceptance is
pending the next Windows VM build; local Linux checks do not establish it. The
project version remains 0.1.0: choose/update the next project+lock version before
tagging. CI rejects mismatched tags to prevent repeated self-update offers. No
commit, push, workflow dispatch, tag or publication was performed by this work.


## Saved-download resume regression checks

Resume and Retry failed are separate operations. Regression fixtures cover a
cancelled batch with completed, failed and never-started hashes; restoration
from multiple older reports; repeated resume with no failed-entry network calls;
and explicit retry of failed rows. Qt checks confirm the remaining/failed totals
stay consistent through pause, close/reopen, resume and cancel.

Synthetic Songs folders simulate osu! consuming an archive. Exact installed
`.osu` MD5s are recognised without downloads; later restores use verified file
identity/timestamps. Wrong revisions and changed cached files are not accepted.
Report tests check app-data storage, a maximum of 10 reports, durable failure
states after old reports disappear, and preservation of archives and queue files.
The packaged smoke and screenshot harnesses use isolated report directories.


## Public release asset assembly

The public assembler emits only the Windows EXE, Linux executable, SHA256SUMS and
CollectionsStudio-sources-and-notices.zip. Regression tests inspect the combined
archive and its inner checksums to ensure application/library sources and both
platform notice ZIPs retain their original bytes. Missing, extra, modified or
wrong-platform inputs are rejected before creating public files. Existing output
directories are never overwritten. Both updater platform paths download and
verify their executable using a synthetic four-file release and its real generated
checksum manifest. The native build/rehearsal gates remain enabled on both runners.
