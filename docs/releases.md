# Windows and Linux releases

The GitHub Actions workflow `.github/workflows/release.yml` builds natively on
the repository's Windows Server 2022 x64 and Ubuntu 22.04 x64 self-hosted runners.
Their names/custom labels are `collections-studio-windows` and
`collections-studio-linux`; both also need their default self-hosted, OS and X64
labels. The output applications are:

- `CollectionsStudio-windows-x64.exe`: one portable Windows executable, with no installer.
- `CollectionsStudio-linux-x64`: one Linux executable, with no AppImage or FUSE requirement.

Python, Qt and the self-contained Realm/.NET helper are embedded and unpacked into
a temporary directory while the app runs. Neither Python nor .NET needs a separate
installation. This is not a fully static Linux executable: glibc 2.35+ and normal
desktop/OpenGL/X11/Wayland system libraries are required. The temporary directory
must permit execution. On Linux, run `chmod +x CollectionsStudio-linux-x64` after
downloading, then `./CollectionsStudio-linux-x64`.

## Build VM setup

Each runner uses its own installation/work directory and service. Windows needs
a machine-wide Git for Windows installation, including Git Bash, accessible to
the runner service account. The workflow locates Git Bash without changing the
VM's global PATH. On Ubuntu, install Qt/X11/OpenGL runtime libraries, Tcl/Tk,
`xvfb`, `xauth` and `binutils` (provides `strip`) once as an administrator. Jobs
check these tools and do not run sudo or apt. Python and the pinned .NET SDK are installed in writable locations
by the workflow; no administrator service account is required for building.
The output path includes the run ID/attempt so an interrupted old build cannot
collide with a later build.

The build jobs receive read-only repository permissions. The tagged publication
job stays on GitHub-hosted Ubuntu and receives contents-write permission only
after both builds pass. This workflow accepts trusted manual runs and version
tags; it has no pull-request trigger. Keep public-repository runner jobs away
from production credentials/data; separate installation directories do not
isolate jobs sharing the same OS account or VM.

## Triggering a build or release

After the repository is on GitHub, a manual **Actions → Desktop releases → Run
workflow** run builds and retains downloadable workflow artifacts only. Pushing a
tag such as `v0.1.0` builds both platforms, tests them, and creates a GitHub Release
only after both builds succeed. A tag containing a hyphen, such as `v0.1.0-beta.1`,
creates a prerelease. Existing releases/assets are not overwritten by reruns.
No custom token is needed; only the release job receives `contents: write`.
Creating this workflow locally does not run it, create a tag, or publish anything.

The workflow installs CPython 3.12.14 through uv's managed distributions on both
platforms. This version is available for Windows through uv, although it is absent
from actions/setup-python's Windows catalogue. It pins uv 0.12.19, .NET SDK 10.0.112, runtime 8.0.31,
the project's Python/NuGet/source locks, and all actions to verified commit SHAs.
Both platforms run the desktop suite and the resulting executable's disposable
`--self-test`. This includes the native Realm assertions and in-app licence/credits
documents, with Python/.NET tools removed from PATH. Passing CI is separate from
manual Windows DPI, live-data-copy and clean-machine acceptance. Binaries are unsigned.

## Updater versioning and native rehearsal

The executable embeds its application version from pyproject.toml (or the matching
release tag), independently of Python/.NET versions. Bump the project version and
uv.lock together before tagging. CI refuses a tag that differs from the project
version, preventing a released client from repeatedly offering itself as an update.
Stable updater tags use `vMAJOR.MINOR.PATCH`; prerelease tags keep the existing
hyphen convention and are excluded from automatic stable updates.

The updater uses the existing platform executable and SHA256SUMS assets on that
GitHub release. Keep both filenames unchanged. No extra update feed or hosting
service is needed. Both executable builds retain notices inside the app, and the
release retains matching sources and notices in the combined support archive.

Every one-file build also runs `scripts/check_portable_update.py` on private
copies: old process exit, executable replacement, restarted GUI acknowledgement
and helper cleanup must succeed. The test uses an isolated profile, no game
database and no live HTTP. It verifies the fixture process image before stopping
that fixture. The stager refuses new versioned builds without the native rehearsal
and frozen updater checks, and includes the rehearsal receipt in the notices ZIP.
This is run natively on both configured runners; local Linux testing alone does
not establish Windows acceptance. Manual unsigned-Windows/Defender/desktop checks
remain separate.

## Licence and source assets

The workflow uploads exactly four public files:

- `CollectionsStudio-windows-x64.exe`
- `CollectionsStudio-linux-x64`
- `SHA256SUMS`
- `CollectionsStudio-sources-and-notices.zip`

Download the executable for your platform to run the app. The updater continues to
use the same executable names and `SHA256SUMS`; checksums cover both binaries and
the combined archive. CI's per-platform build artifacts remain separate internally.
GitHub also adds its standard repository source ZIP/tarball links automatically;
these are separate from the four workflow-uploaded files.
Both tagged releases and build-only workflow runs produce the four-file
`public-release` artifact. Only tag pushes publish it to GitHub Releases.
The release assembler checks both builds' manifests, native updater receipts and
locked upstream source hashes, and rejects missing or unexpected input files.

The combined archive retains the original files byte-for-byte: `application/`
contains the exact tagged application source (`CollectionsStudio-source.tar.gz`),
`libraries/` contains the matching Qt/PySide/Shiboken archives, and `notices/`
contains both platform notice ZIPs, including rebuild instructions and build/test
records. `CONTENTS-SHA256SUMS` hashes those nested files. Nothing in this archive
needs extracting to run the app. Notices are also embedded and readable
through Tools → Credits and licences. Keep the combined archive with any
redistribution. They cover the library notices and the source/recombination route
under LGPLv3 section 4(d)(0); publishing only the EXE/ELF omits that release material.
The application remains MIT licensed and permits rebuilding with modified libraries.

## Building locally and replacing libraries

Build on the matching OS with the documented SDK and pinned interpreter:

```sh
uv sync --frozen --extra desktop --extra desktop-build --python 3.12.14
uv run --frozen --extra desktop --extra desktop-build python desktop/build_desktop.py \
  --onefile --profile release --output artifacts/my-single-file-build
```

The executable is in `artifacts/my-single-file-build/dist/`. Omitting `--onefile`
retains the portable folder layout, with Qt libraries directly replaceable in
`_internal/`. The source and one-file recipes use the same Python/Realm engines.

### Release and debug packaging profiles

CI explicitly selects `--profile release`. On Linux this strips native symbol
tables and omits the optional GTK platform-theme plugin before dependency analysis,
avoiding its GTK/system-ICU dependency chain. The app uses Fusion styling; X11,
Wayland, the desktop portal, image formats and Qt's own ICU libraries remain.
The build audits required platform plugins and runs the complete frozen self-test.
Python, Qt and .NET remain bundled; no new runtime installation is required.

Use `--profile debug`, or omit `--profile`, for the original packaging: no symbol
stripping and no plugin exclusions. This packaging profile preserves the existing
helper's .NET Release compilation and GUI settings. Windows packaging currently
stays unchanged in either profile; Linux stripping is never applied to Windows.
`build-info.json` records the profile, optimizations, binary size and Linux release
plugin list. Licence notices and matching sources remain included in both profiles.

.NET trimming remains disabled. An isolated locked-restore trial with trimming
enabled required a new `Microsoft.NET.ILLink.Tasks` 8.0.31 dependency and failed
with NU1004. Updating that lock and establishing Realm/reflection-based JSON
compatibility require separate work; no dependency locks were relaxed or changed.

To rebuild against modified Qt/PySide/Shiboken, extract the combined archive, then
the application and matching upstream source archives inside it. Build the changed
libraries/wheels using the instructions
in those source trees. In the prepared application environment, install your
compatible modified wheels/libraries, then invoke the builder through that
environment's Python, or use `uv run --no-sync` so a sync does not replace your
changes. `--onefile` makes a new standalone executable; omit it for direct shared
library replacement. No signing key, service credential or publisher approval is
required to build and run your modified application. If redistributing modified
libraries, update notices and source lock URLs/hashes to describe the actual
corresponding sources you provide. The notice collector deliberately rejects
archives whose bytes do not match the selected source lock.

References: [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html),
[LGPLv3 text included with Qt](https://github.com/qt/qtbase/blob/v6.12.0/LICENSES/LGPL-3.0-only.txt),
[Qt licence requirements](https://www.qt.io/development/open-source-lgpl-obligations),
and [GitHub workflow tokens](https://docs.github.com/actions/reference/authentication-in-a-workflow).
