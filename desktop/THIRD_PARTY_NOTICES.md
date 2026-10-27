# Collections Studio — third-party notices

Collections Studio's first-party code is licensed under **MIT**, as selected by
the owner. The complete text is in the top-level LICENSE file. This grant applies
to the project's own code; the third-party components below retain their own terms.
See CREDITS.md for libraries, tools, services and format/documentation references.
Both documents and this notice are readable in the application's Credits and
licences viewer and retained in portable builds. A local build does not establish
that every dependency distribution obligation is complete.

## Dependency audit

| Component | Version | License / role | Distribution considerations |
| --- | --- | --- | --- |
| CPython | 3.12.14 build interpreter | PSF license and included third-party terms | Bundled by PyInstaller; retain Python and bundled OpenSSL/libffi/etc. notices. |
| Microsoft VC++ runtime DLLs | Conditional Windows native dependencies | Microsoft redistributable terms | Inspect the Windows bundle's collected native DLLs and retain applicable Microsoft notices. Do not relicense them under the project's license or assume they are present on a clean machine. This remains part of Windows package acceptance. |
| PySide6 Essentials, Shiboken6 | 6.12.0 | LGPLv3/GPL alternatives or commercial | This Widgets preview uses Qt Core, Gui and Widgets under the LGPL option. Retain license texts and third-party notices; supply the corresponding library source as required. Keep shared libraries replaceable and allow reverse engineering for debugging library modifications. |
| Qt plugins and native dependencies | From the pinned wheel, platform dependent | Mixed third-party terms listed in wheel licenses | Audit the final binary/plugin list. Do not add GPL-only Qt modules without revisiting the project license. No QML, Qt Quick, WebEngine or artwork is used. |
| PyInstaller | 6.22.3 | GPLv2 with bootloader exception; some Apache-2.0 files | The exception permits distributing a built application under its own compatible terms. It does not waive dependencies' obligations. Portable builds, no UPX; one-file releases include sources and rebuilding instructions. |
| pyinstaller-hooks-contrib | Locked by uv | Apache-2.0/GPLv2 alternatives | Build-time hooks; retain packaged notices. |
| altgraph, packaging, setuptools, Windows pefile/pywin32-ctypes | See uv.lock and generated manifest | MIT or their recorded permissive terms | Primarily build-time dependencies; preserve their actual installed metadata and license files. |
| .NET runtime | 8.0.31 | MIT plus runtime third-party notices | The helper is published self-contained, untrimmed, with the runtime beside it. Retain runtime license and third-party notices. The SDK is build-only. |
| Realm .NET and Realm Core | 20.1.0 | Apache-2.0 | Native win-x64 and linux-x64 wrappers are present. Preserve notices and any upstream attribution. Local database only, no Atlas/Sync service. |
| MongoDB.Bson | 2.21.0 | Apache-2.0 | Runtime dependency of Realm; retain its LICENSE.md and nuspec attribution. |
| Remotion.Linq | 2.2.0 | Apache-2.0 | Runtime dependency; retain license and attribution. |
| System.* / Microsoft.* packages | Locked in RID lock files | MIT / recorded Microsoft license URLs | Some are framework/build compatibility packages. Collect all locked package metadata rather than assuming only the direct Realm reference matters. |
| Fody | 6.9.1 | MIT (package License.txt) | Build-only transitive dependency; model weaving is disabled. |

The Flask website, Gunicorn, Requests and Pillow are not imported or included in
this desktop executable. Tkinter stays available from the original source entry
point but is excluded from the Qt bundle. Missing-map downloading uses urllib,
hashlib and zipfile from Python's standard library; there is no curl/7-Zip/shell
runtime dependency.

`collect_notices.py` copies installed wheel license trees, package metadata,
NuGet license files/nuspecs, and pinned Python/.NET/Apache license texts into
`_internal/notices/`. The installed PySide6/Shiboken 6.12 wheels contain license
metadata but no license files, so the builder also fetches the official tagged
Qt Base, SVG, Wayland and PySide/Shiboken source trees, retains their complete
archives under `corresponding-sources/`, and copies their license, attribution and
copyright files into notices. The manifest records URLs and source SHA-256s.
`dependency-manifest.json` records exact identities, the short
`nuget/<package ID>/package.nuspec` metadata filename and each copied NuGet license
path. Original metadata/license contents are retained. This is preparation, not
an automated legal compliance certification. Before any
redistribution, review all copied notices against `bundle-sha256.json`, including
Qt platform/image plugins, OpenSSL and Python's native libraries. Supply exact
matching Qt/PySide/Shiboken and other required corresponding sources with the
distribution or a compliant, durable source mechanism. An upstream homepage link
alone is not a substitute for satisfying source delivery obligations.

The default folder build keeps Qt as replaceable shared libraries. The optional
single-file build unpacks the same dynamic libraries at runtime and is distributed
with corresponding application/Qt/PySide/Shiboken sources and rebuilding instructions
for the LGPLv3 4(d)(0) route; see docs/releases.md. Do not restrict modification,
recombination or reverse engineering for debugging library changes. The first-party
MIT licence does not replace dependency terms. Retain the full notice/source assets
when redistributing either build format.

## Primary references

- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/)
- [Qt LGPL obligations and GPL-only modules](https://www.qt.io/development/open-source-lgpl-obligations)
- [PyInstaller license and bootloader exception](https://pyinstaller.org/en/stable/license.html)
- [Python license](https://docs.python.org/3/license.html)
- [Realm .NET license](https://github.com/realm/realm-dotnet/blob/20.1.0/LICENSE)
- [.NET runtime license and third-party notices](https://github.com/dotnet/runtime/tree/v8.0.31)
