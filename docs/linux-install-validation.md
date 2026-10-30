# Built-in Linux install/uninstall validation — v0.1.5

The Linux standalone binary and AppImage share a per-user installation manager:
Tools → Install / uninstall, plus a header action when running a portable download.
The managed executable, icon, launcher and optional desktop shortcut use one stable
installation location. Switching formats and repeat installs reuse that location.
The original download and running window remain intact. A launcher Uninstall action
opens the manager; removal requires explicit confirmation. Source Python cannot be
installed as the executable. Windows remains portable without this Linux installer.

Only registered, validated app paths are removed. Collections, settings, credentials,
song caches, downloads and reports are outside the removal scope. Custom or relocated
shortcut files are retained and listed. Pre-existing custom files replaced during
installation are backed up privately. Symbolic-link destinations, special files and
forged path records are rejected. Publishing uses staged files, source/target identity
and hash checks, rollback copies and the existing executable updater lock. Concurrent
edits encountered during rollback are preserved with a recovery-copy path. The updater
can replace an installed standalone binary without breaking ownership/removal.

The same existing project SVG is now a shared source asset, bundled into both formats
and used as the installed icon. The GUI uses the corresponding desktop-file ID.
Native packaged self-tests require icon rendering plus install/uninstall in an
explicit temporary layout, without touching the user's installation or game data.

Verified locally:

- **414 desktop tests passed** with synthetic data and Qt offscreen rendering.
- Linux filesystem tests cover binary/AppImage installs, repeat/self installs,
  format switching, source replacement during copy, cancellation, symlinks,
  forged manifests, legacy shortcut backup, custom/relocated shortcut preservation,
  atomic rollback, concurrent-edit recovery and updater lock contention.
- GUI tests cover install, uninstall confirmation/cancellation, close/reopen,
  preserved collection work, a live window after removal and disabled reinstall
  after its running installed file is removed. The dialog was visually reviewed.
- Generated desktop entries passed desktop-file-validate with escaped paths.
- A fresh Linux one-file release-profile preview passed its packaged icon and
  install/uninstall checks and the existing native private-copy updater rehearsal.
- The corresponding AppImage passed its actual packaged self-test, including outer
  AppImage installation/removal and shared icon checks, using extraction fallback.
- Ruff lint/format pass. No new dependency version or system package was installed.

Tests used private temporary layouts, profiles and fixtures. No real installation,
credentials, collections or existing app process was changed or closed. The local
preview was built on Arch; Ubuntu release-runner and physical desktop/menu acceptance
remain for the next release. No Windows installer support or acceptance is claimed.
The earlier local preview used 0.1.4 metadata; the release source is bumped to 0.1.5.

The v0.1.5 workflow uses `max-parallel: 1` to limit the platform matrix to one
build at a time. Final release-source checks passed: 414 tests, Ruff lint/format,
lockfile consistency and whitespace validation. Native Windows and Ubuntu builds,
packaged self-tests and release assembly run before the workflow publishes assets.
