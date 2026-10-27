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
