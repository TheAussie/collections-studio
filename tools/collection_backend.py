"""Toolkit-independent access to the existing verified Realm helper."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "tools" / "RealmCollectionImport" / "RealmCollectionImport.csproj"
DLL = PROJECT.parent / "bin" / "Release" / "net8.0" / "realm-collection-import.dll"


class Backend:
    def __init__(self):
        self.ready = False

    def run(self, command, **options):
        bundled = (
            Path(getattr(sys, "_MEIPASS", ROOT))
            / "backend"
            / (
                "realm-collection-import.exe"
                if sys.platform == "win32"
                else "realm-collection-import"
            )
        )
        if getattr(sys, "frozen", False) and not bundled.is_file():
            raise RuntimeError(
                "The bundled Realm helper is missing. Reinstall the complete application folder."
            )
        if bundled.is_file():
            return self._execute([str(bundled)], command, options)
        if not self.ready:
            built = subprocess.run(
                [
                    "dotnet",
                    "build",
                    str(PROJECT),
                    "-c",
                    "Release",
                    "-p:RestoreLockedMode=true",
                    "--nologo",
                ],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=ROOT,
                check=False,
            )
            if built.returncode:
                raise RuntimeError("Backend build failed:\n" + built.stdout + built.stderr)
            self.ready = True
        return self._execute(["dotnet", str(DLL)], command, options)

    def _execute(self, prefix, command, options):
        arguments = [*prefix, command]
        for name, value in options.items():
            arguments.extend(["--" + name.replace("_", "-"), str(value)])
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
            cwd=ROOT,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "The Realm operation failed.")
        return json.loads(result.stdout)
