"""Build a native portable folder or single executable. Never publishes an artifact."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = "10.0.112"
RUNTIME = "8.0.31"


def run(arguments, **options):
    print("Running:", " ".join(map(str, arguments)), flush=True)
    return subprocess.run(list(map(str, arguments)), check=True, **options)


def check_sdk(parser):
    try:
        sdk = subprocess.check_output(
            ["dotnet", "--version"],
            text=True,
            stderr=subprocess.STDOUT,
            cwd=ROOT / "desktop",
        ).strip()
    except FileNotFoundError:
        parser.error(
            f"dotnet.exe was not found on PATH. Install .NET SDK {SDK} for x64, "
            "then close and reopen PowerShell. Verify with: dotnet --list-sdks"
        )
    except subprocess.CalledProcessError:
        parser.error(
            f".NET SDK {SDK} is unavailable. Run dotnet --list-sdks and install "
            f"that exact SDK version; desktop/global.json pins {SDK}."
        )
    if sdk != SDK:
        parser.error(f"Install .NET SDK {SDK}; found {sdk}.")


def check_linux_release_plugins(bundle, binary, onefile):
    if onefile:
        from PyInstaller.archive.readers import CArchiveReader

        names = CArchiveReader(str(binary)).toc
    else:
        names = [
            path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()
        ]
    plugin_root = "PySide6/Qt/plugins/"
    plugins = {name.split(plugin_root, 1)[1] for name in names if plugin_root in name}
    required = {"platforms/libqxcb.so", "platforms/libqwayland.so", "platforms/libqoffscreen.so"}
    if not required <= plugins or "platformthemes/libqgtk3.so" in plugins:
        raise RuntimeError("Linux release must retain X11/Wayland/offscreen plugins and omit GTK.")
    return sorted(plugins)


def application_version(parser):
    from packaging.version import InvalidVersion, Version

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    tag = os.environ.get("COLLECTIONS_STUDIO_RELEASE_TAG", "")
    if tag:
        try:
            matches = bool(
                re.fullmatch(
                    r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?", tag
                )
            ) and Version(tag[1:]) == Version(version)
        except InvalidVersion:
            matches = False
        if not matches:
            parser.error(
                "Release tag does not match pyproject.toml. "
                "Update the project version and uv.lock before tagging."
            )
        version = tag[1:]
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "desktop-build")
    parser.add_argument("--rid", choices=["win-x64", "linux-x64"])
    parser.add_argument(
        "--profile",
        choices=["debug", "release"],
        default="debug",
        help="Packaging profile: debug preserves the original bundle; release optimizes Linux size",
    )
    parser.add_argument(
        "--onefile", action="store_true", help="Bundle everything in one executable"
    )
    parser.add_argument(
        "--prepare-lock", action="store_true", help="Maintainer: create a new RID lock"
    )
    args = parser.parse_args()
    if sys.platform not in ("win32", "linux"):
        parser.error("This preview build recipe currently targets Windows and Linux.")
    host = "win-x64" if sys.platform == "win32" else "linux-x64"
    rid = args.rid or host
    if platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("This preview recipe targets x64 only.")
    if sys.version_info[:3] != (3, 12, 14):
        parser.error("Build using pinned CPython 3.12.14.")
    if rid != host and not args.prepare_lock:
        parser.error("PyInstaller must run on the target OS; Windows cannot be built on Linux.")
    linux_release = args.profile == "release" and host == "linux-x64"
    if linux_release and not args.prepare_lock and not shutil.which("strip"):
        parser.error("Linux release builds require strip from binutils on PATH.")
    check_sdk(parser)
    version = application_version(parser)
    output = args.output.resolve()
    if output.exists():
        parser.error("Choose a new output folder; builds never overwrite an earlier bundle.")
    output.mkdir(parents=True)
    source = output / "helper-source"
    source.mkdir()
    for pattern in ("*.cs", "*.csproj"):
        for file in (ROOT / "tools" / "RealmCollectionImport").glob(pattern):
            shutil.copy2(file, source / file.name)
    shutil.copy2(ROOT / "desktop" / "global.json", output / "global.json")
    project = source / "RealmCollectionImport.csproj"
    locked = ROOT / "desktop" / f"realm-{rid}.lock.json"
    if args.prepare_lock:
        if locked.exists():
            parser.error("RID lock already exists. Review dependency updates separately.")
        shutil.copy2(
            ROOT / "tools" / "RealmCollectionImport" / "packages.lock.json",
            source / "packages.lock.json",
        )
        run(
            [
                "dotnet",
                "restore",
                project,
                "-r",
                rid,
                "--force-evaluate",
                f"-p:RuntimeFrameworkVersion={RUNTIME}",
            ],
            cwd=source,
        )
        shutil.copy2(source / "packages.lock.json", locked)
        print("Prepared:", locked)
        return
    shutil.copy2(locked, source / "packages.lock.json")
    run(
        [
            "dotnet",
            "restore",
            project,
            "-r",
            rid,
            "--locked-mode",
            f"-p:RuntimeFrameworkVersion={RUNTIME}",
        ],
        cwd=source,
    )
    run(
        [
            "dotnet",
            "publish",
            project,
            "-c",
            "Release",
            "-r",
            rid,
            "--self-contained",
            "true",
            "--no-restore",
            f"-p:RuntimeFrameworkVersion={RUNTIME}",
            "-p:PublishSingleFile=false",
            # Reflection-based JSON and Realm schema access need separate trim compatibility work.
            "-p:PublishTrimmed=false",
            "-o",
            output / "backend",
        ],
        cwd=source,
    )
    sys.path.insert(0, str(ROOT / "desktop"))
    from collect_notices import collect, copy_project_documents

    collect(output / "notices", rid)
    (output / "app-version.json").write_text(
        json.dumps({"version": version, "format": "onefile" if args.onefile else "onedir"}),
        encoding="utf-8",
    )
    environment = dict(
        os.environ,
        COLLECTIONS_STUDIO_STAGE=str(output),
        COLLECTIONS_STUDIO_ONEFILE="1" if args.onefile else "0",
        COLLECTIONS_STUDIO_PROFILE=args.profile,
    )
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            output / "dist",
            "--workpath",
            output / "pyinstaller",
            ROOT / "desktop" / "collections-studio.spec",
        ],
        cwd=ROOT,
        env=environment,
    )
    bundle = output / "dist" if args.onefile else output / "dist" / "CollectionsStudio"
    copy_project_documents(bundle)
    shutil.copy2(ROOT / "desktop" / "README.md", bundle / "BUILD_AND_TEST.md")
    binary = bundle / ("CollectionsStudio.exe" if host == "win-x64" else "CollectionsStudio")
    release_plugins = (
        check_linux_release_plugins(bundle, binary, args.onefile) if linux_release else None
    )
    if host == "linux-x64" and not args.onefile:
        (bundle / "_internal" / "backend" / "realm-collection-import").chmod(0o755)
    report = output / "packaged-self-test.json"
    # A private empty profile and a PATH without Python/dotnet exercise the frozen bundle.
    with tempfile.TemporaryDirectory(prefix="studio-clean-profile-") as profile:
        environment = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            environment.pop(name, None)
        environment.update(
            XDG_CONFIG_HOME=str(Path(profile) / "config"),
            XDG_CACHE_HOME=str(Path(profile) / "cache"),
            LOCALAPPDATA=str(Path(profile) / "local"),
            APPDATA=str(Path(profile) / "roaming"),
        )
        environment["PATH"] = (
            str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
            if host == "win-x64"
            else ""
        )
        if host == "linux-x64":
            environment["QT_QPA_PLATFORM"] = "offscreen"
        run([binary, "--self-test", "--report", report], cwd=profile, env=environment)
    if not report.is_file() or not json.loads(report.read_text(encoding="utf-8"))["Frozen"]:
        raise RuntimeError("The packaged self-test did not produce a frozen success report.")
    if args.onefile:
        run(
            [
                sys.executable,
                ROOT / "scripts" / "check_portable_update.py",
                "--binary",
                binary,
                "--version",
                version,
                "--output",
                output / "update-rehearsal",
            ]
        )
        rehearsal = json.loads(
            (output / "update-rehearsal/native-update-rehearsal.json").read_text(encoding="utf-8")
        )
        if not rehearsal["Passed"]:
            raise RuntimeError("The native portable update rehearsal failed.")
    manifest = {
        str(path.relative_to(bundle)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(bundle.rglob("*"))
        if path.is_file()
    }
    (output / "bundle-sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "build-info.json").write_text(
        json.dumps(
            {
                "Format": "onefile" if args.onefile else "onedir",
                "BuildProfile": args.profile,
                "ApplicationVersion": version,
                "NativeUpdateRehearsal": bool(args.onefile),
                "LinuxSizeOptimizations": linux_release,
                "RealmTrimming": False,
                "LinuxReleaseQtPlugins": release_plugins,
                "RuntimeIdentifier": rid,
                "Python": ".".join(map(str, sys.version_info[:3])),
                "DotnetSDK": SDK,
                "DotnetRuntime": RUNTIME,
                "Binary": str(binary.relative_to(output)),
                "BinaryBytes": binary.stat().st_size,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Local portable build:", binary if args.onefile else bundle)
    print(
        "No publication performed. Project licence: MIT. Dependency/source review remains required."
    )


if __name__ == "__main__":
    main()
