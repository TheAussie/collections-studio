# Collections Studio credits

Collections Studio is developed by TheAussie and contributors. Its first-party
code is available under the MIT licence: you may copy, modify, redistribute,
sublicense and use it commercially, retaining its copyright and licence notice.
Third-party components retain their own copyrights and licence terms.

Thank you to the authors, maintainers and communities behind the following
libraries, tools, services and references used during development.

## Interface, runtime and packaging

- Python / CPython and its standard library — the Python Software Foundation and
  Python contributors. https://www.python.org/
- Qt, PySide6 Essentials and Shiboken6 — The Qt Company and Qt contributors;
  the Qt interface and Python bindings. https://www.qt.io/ and
  https://doc.qt.io/qtforpython-6/
- Tcl/Tk and Python's tkinter — the classic interface.
  https://www.tcl-lang.org/ and https://docs.python.org/3/library/tkinter.html
- .NET runtime and SDK — Microsoft and .NET contributors; native helper runtime
  and build tools. https://dotnet.microsoft.com/
- Realm .NET / Realm Core — Realm, MongoDB and contributors; local Realm access.
  https://github.com/realm/realm-dotnet
- MongoDB.Bson and Remotion.Linq — native helper dependencies.
  https://github.com/mongodb/mongo-csharp-driver and https://github.com/re-motion/Relinq
- PyInstaller, pyinstaller-hooks-contrib, altgraph, packaging, setuptools,
  macholib, pefile and pywin32-ctypes — application bundling and platform support.
  https://pyinstaller.org/
- Python/.NET/Qt native components, including OpenSSL, libffi and platform
  libraries when present — their respective authors. Original notices and the
  exact shipped components are recorded in the build's notices and manifest.
- Microsoft Visual C++ redistributable components, when included in a Windows
  bundle — Microsoft; their separate distribution terms apply.

## Formats and compatibility references

- osu! and osu!lazer — ppy and osu! contributors; the collection and inventory
  formats with which this editor interoperates. https://github.com/ppy/osu
- ppy's legacy database format documentation — reference for collection.db and
  osu!.db parsing. https://github.com/ppy/osu/wiki/Legacy-database-file-structure
- Replay Parser — the existing beatmap-index-cache.json contract and
  path/size/mtime cache approach were compatibility references for cache import
  and Songs scans. Replay Parser remains a separate project.
- The version-1 Maps collection snapshot contract — interchange with the
  separate collection-link producer; documented in docs/collection-api.md.

## Collection and beatmap services

- osu!collector — public collection import and metadata.
  https://osucollector.com/
- osu.direct — beatmap lookup/download API. https://osu.direct/api/docs
- Mirria — beatmap lookup/download API. https://mirror.lisek.cc/docs
- Nerinyan — beatmap downloads and route documentation.
  https://github.com/Nerinyan/nerinyan-api-v2
- Sayobot — beatmap downloads and API documentation.
  https://www.showdoc.com.cn/SoulDee
- Nekoha — beatmap downloads and frontend endpoint reference.
  https://mirror.nekoha.moe/
- Beatconnect — beatmap downloads. https://beatconnect.io/
- osu!dl — beatmap downloads and public route reference.
  https://osudl.org/ and https://github.com/kaysting/osudl
- Hinamizawa — beatmap lookup/download API.
  https://mirror.hinamizawa.ai/docs/beatmap-info and
  https://mirror.hinamizawa.ai/docs/beatmap-download

## Development tools and assistance

- uv — Astral and contributors; dependency locking and environments.
  https://docs.astral.sh/uv/
- pytest, pluggy, iniconfig, Pygments and colorama — testing and test output.
  https://docs.pytest.org/
- Ruff — Astral and contributors; linting and formatting.
  https://docs.astral.sh/ruff/
- Fody — contributors to the native helper's build-time dependency.
  https://github.com/Fody/Fody
- OpenAI Codex — programming, refactoring and verification assistance.
  https://openai.com/codex/
- SPDX and Choose a License — licence identification and MIT licence reference.
  https://spdx.org/licenses/MIT.html and https://choosealicense.com/licenses/mit/

## Licence texts and exact dependency inventories

The Project licence tab contains the complete MIT licence. The Third-party
notices tab describes dependency terms and source delivery requirements. Built
distributions also retain original licence/copyright files and
dependency-manifest.json under their notices directory, and the top-level LICENSE,
CREDITS.md and THIRD_PARTY_NOTICES.md documents. These acknowledgements supplement
the original legal notices. Exact Python versions are pinned in uv.lock; the
native helper's locked dependencies are listed below (across both supported RIDs).

## Locked native helper dependencies

- Fody — 6.9.1
- Microsoft.CSharp — 4.5.0
- Microsoft.NETCore.Platforms — 1.1.0
- Microsoft.NETCore.Targets — 1.1.0
- Microsoft.Win32.Primitives — 4.3.0
- MongoDB.Bson — 2.21.0
- Realm — 20.1.0
- Remotion.Linq — 2.2.0
- System.Buffers — 4.5.1
- System.Collections — 4.3.0
- System.Collections.Concurrent — 4.3.0
- System.Diagnostics.Debug — 4.3.0
- System.Diagnostics.Tracing — 4.3.0
- System.Dynamic.Runtime — 4.3.0
- System.Globalization — 4.3.0
- System.Globalization.Calendars — 4.3.0
- System.Globalization.Extensions — 4.3.0
- System.IO — 4.3.0
- System.IO.FileSystem — 4.3.0
- System.IO.FileSystem.Primitives — 4.3.0
- System.Linq — 4.3.0
- System.Linq.Expressions — 4.3.0
- System.Linq.Queryable — 4.0.1
- System.Memory — 4.5.5
- System.Net.NameResolution — 4.3.0
- System.Net.Primitives — 4.3.0
- System.Net.Security — 4.3.2
- System.Net.Sockets — 4.3.0
- System.Net.WebHeaderCollection — 4.3.0
- System.Net.WebSockets — 4.3.0
- System.Net.WebSockets.Client — 4.3.2
- System.ObjectModel — 4.3.0
- System.Private.Uri — 4.3.0
- System.Reflection — 4.3.0
- System.Reflection.Emit — 4.3.0
- System.Reflection.Emit.ILGeneration — 4.3.0
- System.Reflection.Emit.Lightweight — 4.3.0
- System.Reflection.Extensions — 4.3.0
- System.Reflection.Primitives — 4.3.0
- System.Reflection.TypeExtensions — 4.3.0
- System.Resources.ResourceManager — 4.3.0
- System.Runtime — 4.3.0
- System.Runtime.CompilerServices.Unsafe — 6.0.0
- System.Runtime.Extensions — 4.3.0
- System.Runtime.Handles — 4.3.0
- System.Runtime.InteropServices — 4.3.0
- System.Runtime.Numerics — 4.3.0
- System.Security.Claims — 4.3.0
- System.Security.Cryptography.Algorithms — 4.3.0
- System.Security.Cryptography.Cng — 4.3.0
- System.Security.Cryptography.Csp — 4.3.0
- System.Security.Cryptography.Encoding — 4.3.0
- System.Security.Cryptography.OpenSsl — 4.3.0
- System.Security.Cryptography.Primitives — 4.3.0
- System.Security.Cryptography.X509Certificates — 4.3.0
- System.Security.Principal — 4.3.0
- System.Security.Principal.Windows — 4.3.0
- System.Text.Encoding — 4.3.0
- System.Text.Encoding.Extensions — 4.3.0
- System.Threading — 4.3.0
- System.Threading.Channels — 6.0.0
- System.Threading.Overlapped — 4.3.0
- System.Threading.Tasks — 4.3.0
- System.Threading.ThreadPool — 4.3.0
- System.Threading.Timer — 4.3.0
- runtime.any.System.Collections — 4.3.0
- runtime.any.System.Diagnostics.Tracing — 4.3.0
- runtime.any.System.Globalization — 4.3.0
- runtime.any.System.Globalization.Calendars — 4.3.0
- runtime.any.System.IO — 4.3.0
- runtime.any.System.Reflection — 4.3.0
- runtime.any.System.Reflection.Extensions — 4.3.0
- runtime.any.System.Reflection.Primitives — 4.3.0
- runtime.any.System.Resources.ResourceManager — 4.3.0
- runtime.any.System.Runtime — 4.3.0
- runtime.any.System.Runtime.Handles — 4.3.0
- runtime.any.System.Runtime.InteropServices — 4.3.0
- runtime.any.System.Text.Encoding — 4.3.0
- runtime.any.System.Text.Encoding.Extensions — 4.3.0
- runtime.any.System.Threading.Tasks — 4.3.0
- runtime.any.System.Threading.Timer — 4.3.0
- runtime.debian.8-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.fedora.23-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.fedora.24-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.native.System — 4.3.0
- runtime.native.System.Net.Http — 4.3.0
- runtime.native.System.Net.Security — 4.3.0
- runtime.native.System.Security.Cryptography.Apple — 4.3.0
- runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.opensuse.13.2-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.opensuse.42.1-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.osx.10.10-x64.runtime.native.System.Security.Cryptography.Apple — 4.3.0
- runtime.osx.10.10-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.rhel.7-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.ubuntu.14.04-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.ubuntu.16.04-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.ubuntu.16.10-x64.runtime.native.System.Security.Cryptography.OpenSsl — 4.3.2
- runtime.unix.Microsoft.Win32.Primitives — 4.3.0
- runtime.unix.System.Diagnostics.Debug — 4.3.0
- runtime.unix.System.IO.FileSystem — 4.3.0
- runtime.unix.System.Net.Primitives — 4.3.0
- runtime.unix.System.Net.Sockets — 4.3.0
- runtime.unix.System.Private.Uri — 4.3.0
- runtime.unix.System.Runtime.Extensions — 4.3.0
- runtime.win.Microsoft.Win32.Primitives — 4.3.0
- runtime.win.System.Diagnostics.Debug — 4.3.0
- runtime.win.System.IO.FileSystem — 4.3.0
- runtime.win.System.Net.Primitives — 4.3.0
- runtime.win.System.Net.Sockets — 4.3.0
- runtime.win.System.Runtime.Extensions — 4.3.0


## Release automation

- GitHub Releases and its public REST API — version checks and application updates.
  https://docs.github.com/en/rest/releases
- GitHub Actions and the maintained actions/checkout, actions/setup-python,
  actions/setup-dotnet, actions/upload-artifact and actions/download-artifact
  actions — native builds and release artifact transfer. https://github.com/actions
- Astral's setup-uv action — locked Python toolchain setup in CI.
  https://github.com/astral-sh/setup-uv
