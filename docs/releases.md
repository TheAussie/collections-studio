# Windows and Linux releases

The GitHub Actions workflow `.github/workflows/release.yml` builds natively on
Windows Server 2022 x64 and Ubuntu 22.04 x64. The output applications are:

- `CollectionsStudio-windows-x64.exe`: one portable Windows executable, with no installer.
- `CollectionsStudio-linux-x64`: one Linux executable, with no AppImage or FUSE requirement.

Python, Qt and the self-contained Realm/.NET helper are embedded and unpacked into
a temporary directory while the app runs. Neither Python nor .NET needs a separate
installation. This is not a fully static Linux executable: glibc 2.35+ and normal
desktop/OpenGL/X11/Wayland system libraries are required. The temporary directory
must permit execution. On Linux, run `chmod +x CollectionsStudio-linux-x64` after
downloading, then `./CollectionsStudio-linux-x64`.

## Triggering a build or release

After the repository is on GitHub, a manual **Actions → Desktop releases → Run
workflow** run builds and retains downloadable workflow artifacts only. Pushing a
tag such as `v0.1.0` builds both platforms, tests them, and creates a GitHub Release
only after both builds succeed. A tag containing a hyphen, such as `v0.1.0-beta.1`,
creates a prerelease. Existing releases/assets are not overwritten by reruns.
No custom token is needed; only the release job receives `contents: write`.
Creating this workflow locally does not run it, create a tag, or publish anything.

The workflow pins CPython 3.12.14, uv 0.12.19, .NET SDK 10.0.112, runtime 8.0.31,
the project's Python/NuGet/source locks, and all actions to verified commit SHAs.
Both platforms run the desktop suite and the resulting executable's disposable
`--self-test`. This includes the native Realm assertions and in-app licence/credits
documents, with Python/.NET tools removed from PATH. Passing CI is separate from
manual Windows DPI, live-data-copy and clean-machine acceptance. Binaries are unsigned.

## Licence and source assets

Each release also contains platform notice ZIPs, the exact tagged application
source (`CollectionsStudio-source.tar.gz`), matching Qt/PySide/Shiboken source
archives, and `SHA256SUMS`. They accompany the single application binaries; no
notice ZIP needs extracting to run the app. Notices are also embedded and readable
through Tools → Credits and licences. Keep the notice/source assets with any
redistribution. They cover the library notices and the source/recombination route
under LGPLv3 section 4(d)(0); publishing only the EXE/ELF omits that release material.
The application remains MIT licensed and permits rebuilding with modified libraries.

## Building locally and replacing libraries

Build on the matching OS with the documented SDK and pinned interpreter:

```sh
uv sync --frozen --extra desktop --extra desktop-build --python 3.12.14
uv run --frozen --extra desktop --extra desktop-build python desktop/build_desktop.py \
  --onefile --output artifacts/my-single-file-build
```

The executable is in `artifacts/my-single-file-build/dist/`. Omitting `--onefile`
retains the portable folder layout, with Qt libraries directly replaceable in
`_internal/`. The source and one-file recipes use the same Python/Realm engines.

To rebuild against modified Qt/PySide/Shiboken, extract the application and matching
upstream source assets. Build the changed libraries/wheels using the instructions
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
