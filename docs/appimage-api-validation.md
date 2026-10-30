# AppImage and optional osu! API validation (2026-10-30)

The release workflow adds CollectionsStudio-linux-x64.AppImage and LINUX_INSTALL.md
alongside the existing two executables, SHA256SUMS and combined support archive.
AppImage packaging verifies the staged binary hash, downloads checksum-pinned
appimagetool and matching runtime/dependency sources, and runs the actual image's
self-test in an isolated profile without FUSE. Assembly verifies image/payload/source
hashes and the test receipt; the workflow requires the AppImage. Matching runtime
sources, build recipes, dependency licences and reports stay in the combined support
archive, and runtime notices are appended to the existing Credits viewer.

This first image wraps the existing one-file payload and therefore extracts twice.
It uses manual updates; native automatic replacement refuses AppImage payloads.
The standalone updater and its filenames remain unchanged. AppImage packaging alone
does not address the reported host Fontconfig/XKB mismatch. No claim of fixing those
warnings, native Windows acceptance or distribution-wide compatibility is made.

The optional official API is a final exact-MD5 resolver after enabled mirrors fail.
It applies no rank-status filter, verifies returned hash/IDs, uses public
client-credentials tokens in memory, caches successful lookups and spaces requests
at least 1.05 seconds apart. Rate limiting produces a bounded cooldown and failed
authentication disables that provider until credentials are changed. Existing map
archive verification and mirror downloads remain in control of saved data.

Credentials are entered under Tools → osu! API credentials. Explicit Save uses
Windows Credential Manager or Linux Secret Service through secret-tool; session-only
use skips persistence. Missing/locked storage fails visibly without plaintext fallback.
Only the nonsecret client ID and the provider preference enter QSettings. Tests mock
vault operations and HTTP; no real credentials are accessed or configured.

Checks:

- Full Linux synthetic desktop suite: **393 passed**. One earlier legacy Tk focus/
  grab timing failure passed on a full rerun. Xvfb is absent locally; CI already
  requires it. Qt tests use offscreen rendering.
- New tests cover graveyard/exact-hash resolution, wrong hashes/IDs, caching,
  request spacing, 401/403/404/429/500 handling, cancellation, denied redirects,
  mirror-first fallback, credential stdin/OS-store failures, session-only UI,
  AppImage update refusal, argv forwarding, runtime credits, and release-assembly
  rejection of missing/modified images.
- Native packaging rehearsal used the existing onefile-linux-validation binary
  in private /tmp copies. AppImage creation and its packaged self-test passed.
  This tests the packaging path, not a fresh build of the new application source.
- Ruff lint/format pass. No new Python dependency or system package was installed.

Still required before publishing: build the current source on the existing Windows
and Ubuntu runners, complete the new image's CI self-test and manually check Linux
launch/menu integration, native vault saving and API credentials on the user's machine.
No workflow was dispatched, tag/release created, commit/push or deployment performed.

Primary contracts: https://osu.ppy.sh/docs/index.html#lookup-beatmap and
https://osu.ppy.sh/docs/index.html#client-credentials-grant;
https://github.com/AppImage/AppImageKit/wiki/Creating-AppImages.
