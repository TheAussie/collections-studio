"""Stage verified binaries/notices/sources and checksums; never uploads anything."""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLES = {
    "win-x64": ("CollectionsStudio.exe", "CollectionsStudio-windows-x64.exe"),
    "linux-x64": ("CollectionsStudio", "CollectionsStudio-linux-x64"),
}
SUPPORT_ARCHIVE = "CollectionsStudio-sources-and-notices.zip"
PUBLIC_ASSETS = {name for _, name in EXECUTABLES.values()} | {SUPPORT_ARCHIVE, "SHA256SUMS"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_release(build, rid, output, include_qt_sources=False):
    source_name, release_name = EXECUTABLES[rid]
    binary = build / "dist" / source_name
    info = json.loads((build / "build-info.json").read_text(encoding="utf-8"))
    report = json.loads((build / "packaged-self-test.json").read_text(encoding="utf-8"))
    hashes = json.loads((build / "bundle-sha256.json").read_text(encoding="utf-8"))
    if info["Format"] != "onefile" or info["RuntimeIdentifier"] != rid:
        raise ValueError("Release assets require a single-file build for the requested platform.")
    if not report.get("Frozen") or not report.get("CreditsAndLicenceDocuments"):
        raise ValueError("A successful frozen self-test including credits/licences is required.")
    binary_hash = digest(binary)
    rehearsal = build / "update-rehearsal/native-update-rehearsal.json"
    native = json.loads(rehearsal.read_text(encoding="utf-8")) if rehearsal.is_file() else {}
    if info.get("ApplicationVersion") and (
        not info.get("NativeUpdateRehearsal")
        or not report.get("VersionedUpdateDownloadAndReplacement")
        or not rehearsal.is_file()
        or not native.get("Passed")
        or native.get("Version") != info["ApplicationVersion"]
        or native.get("BinarySha256") != binary_hash
    ):
        raise ValueError("A successful native update rehearsal is required for versioned releases.")
    if binary_hash != hashes[source_name]:
        raise ValueError("The binary differs from the verified build manifest.")
    notices = build / "notices"
    dependencies = json.loads((notices / "dependency-manifest.json").read_text(encoding="utf-8"))
    if dependencies["FirstPartyLicense"] != "MIT":
        raise ValueError("The dependency manifest must record the first-party MIT licence.")
    for filename in ["LICENSE", "CREDITS.md", "THIRD_PARTY_NOTICES.md"]:
        if not (notices / filename).is_file():
            raise ValueError(f"Missing release notice: {filename}")
    sources = json.loads((ROOT / "desktop" / "qt-sources.lock.json").read_text(encoding="utf-8"))
    recorded = {entry["Module"]: entry for entry in dependencies["QtCorrespondingSources"]}
    verified_sources = []
    for entry in sources:
        source = build / "corresponding-sources" / entry["Archive"]
        if (
            recorded[entry["Module"]]["Sha256"] != entry["Sha256"]
            or digest(source) != entry["Sha256"]
        ):
            raise ValueError(f"Corresponding source differs from its lock: {entry['Archive']}")
        verified_sources.append(source)
    # Validate all prerequisites before creating any release output.
    output.mkdir(parents=True)
    destination = output / release_name
    shutil.copy2(binary, destination)
    if rid == "linux-x64":
        destination.chmod(0o755)
    archive = output / f"CollectionsStudio-{rid}-notices.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(notices.rglob("*")):
            if path.is_file():
                bundle.write(path, (Path("notices") / path.relative_to(notices)).as_posix())
        bundle.write(ROOT / "docs" / "releases.md", "REBUILDING.md")
        for filename in ["packaged-self-test.json", "bundle-sha256.json", "build-info.json"]:
            bundle.write(build / filename, filename)
        if info.get("ApplicationVersion"):
            bundle.write(rehearsal, "native-update-rehearsal.json")
    if include_qt_sources:
        for source in verified_sources:
            shutil.copy2(source, output / source.name)
    return destination


def write_checksums(directory):
    files = sorted(
        path for path in directory.iterdir() if path.is_file() and path.name != "SHA256SUMS"
    )
    if not files:
        raise ValueError("No release assets to hash.")
    (directory / "SHA256SUMS").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )


def assemble_release(inputs, output, require_appimage=False):
    """Publishable file set; retain every original source/notice archive byte-for-byte."""
    inputs, output = Path(inputs), Path(output)
    sources = json.loads((ROOT / "desktop/qt-sources.lock.json").read_text(encoding="utf-8"))
    source_names = {entry["Archive"] for entry in sources}
    notice_names = {f"CollectionsStudio-{rid}-notices.zip" for rid in EXECUTABLES}
    application_source = "CollectionsStudio-source.tar.gz"
    appimage = "CollectionsStudio-linux-x64.AppImage"
    appimage_support = "CollectionsStudio-AppImage-support.zip"
    has_appimage = any((inputs / name).exists() for name in (appimage, appimage_support))
    if require_appimage and not has_appimage:
        raise ValueError("The release workflow requires its verified AppImage.")
    required = (
        {name for _, name in EXECUTABLES.values()}
        | source_names
        | notice_names
        | {application_source}
    )
    if has_appimage:
        required |= {appimage, appimage_support}
    if output.exists():
        raise ValueError("Choose an unused final release output directory.")
    if {p.name for p in inputs.iterdir()} != required or any(
        not (inputs / name).is_file() or (inputs / name).is_symlink() for name in required
    ):
        raise ValueError(
            "Release inputs must contain exactly both binaries, notices and locked sources."
        )
    for entry in sources:
        if digest(inputs / entry["Archive"]) != entry["Sha256"]:
            raise ValueError(f"Release source differs from its lock: {entry['Archive']}")
    versions = set()
    for rid, (original, binary) in EXECUTABLES.items():
        with zipfile.ZipFile(inputs / f"CollectionsStudio-{rid}-notices.zip") as notices:
            info = json.loads(notices.read("build-info.json"))
            report = json.loads(notices.read("packaged-self-test.json"))
            hashes = json.loads(notices.read("bundle-sha256.json"))
            dependencies = json.loads(notices.read("notices/dependency-manifest.json"))
            for name in ("LICENSE", "CREDITS.md", "THIRD_PARTY_NOTICES.md"):
                if not notices.read("notices/" + name):
                    raise ValueError(f"Missing platform notice: {name}")
            if (
                info.get("RuntimeIdentifier") != rid
                or info.get("Format") != "onefile"
                or not report.get("Frozen")
                or not report.get("CreditsAndLicenceDocuments")
                or dependencies.get("FirstPartyLicense") != "MIT"
                or hashes.get(original) != digest(inputs / binary)
                or not notices.read("REBUILDING.md")
            ):
                raise ValueError(f"Release inputs differ from the verified {rid} build.")
            recorded = {
                entry["Archive"]: entry["Sha256"]
                for entry in dependencies["QtCorrespondingSources"]
            }
            if any(recorded.get(entry["Archive"]) != entry["Sha256"] for entry in sources):
                raise ValueError(f"Source notices differ from the locked {rid} dependencies.")
            version = info.get("ApplicationVersion")
            versions.add(version)
            if version:
                native = json.loads(notices.read("native-update-rehearsal.json"))
                if (
                    not info.get("NativeUpdateRehearsal")
                    or not report.get("VersionedUpdateDownloadAndReplacement")
                    or not native.get("Passed")
                    or native.get("Version") != version
                    or native.get("BinarySha256") != hashes[original]
                ):
                    raise ValueError(f"Missing matching native updater rehearsal for {rid}.")
    if len(versions) != 1:
        raise ValueError("Both release binaries must have the same application version.")
    if has_appimage:
        lock = json.loads((ROOT / "desktop/appimage.lock.json").read_text())
        with zipfile.ZipFile(inputs / appimage_support) as support:
            proof = json.loads(support.read("build.json"))
            tested = json.loads(support.read("packaged-self-test.json"))
            if (
                proof.get("ImageSha256") != digest(inputs / appimage)
                or proof.get("PayloadSha256") != digest(inputs / EXECUTABLES["linux-x64"][1])
                or not tested.get("Frozen")
                or not tested.get("CreditsAndLicenceDocuments")
                or json.loads(support.read("appimage.lock.json")) != lock
            ):
                raise ValueError("AppImage inputs differ from their verified build.")
            for entry in lock["sources"]:
                if (
                    hashlib.sha256(support.read("sources/" + entry["name"])).hexdigest()
                    != entry["sha256"]
                ):
                    raise ValueError("AppImage corresponding sources changed.")
        if not (ROOT / "docs/linux-install.md").is_file():
            raise ValueError("Linux installation instructions are missing.")
    # Only create the public output after every platform/source check has passed.
    output.mkdir(parents=True)
    for _, name in EXECUTABLES.values():
        shutil.copy2(inputs / name, output / name)
    (output / EXECUTABLES["linux-x64"][1]).chmod(0o755)
    if has_appimage:
        shutil.copy2(inputs / appimage, output / appimage)
        (output / appimage).chmod(0o755)
        shutil.copy2(ROOT / "docs/linux-install.md", output / "LINUX_INSTALL.md")
    contents = {application_source: "application/" + application_source}
    contents.update({name: "libraries/" + name for name in source_names})
    contents.update({name: "notices/" + name for name in notice_names})
    if has_appimage:
        contents[appimage_support] = "notices/" + appimage_support
    with zipfile.ZipFile(output / SUPPORT_ARCHIVE, "x", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr(
            "README.txt",
            (
                "Collections Studio sources and notices\n\n"
                "Run the separate Windows EXE or Linux executable to use the app.\n"
                "This archive retains the exact matching application and library sources,\n"
                "platform licence/credit notices, build records and native updater test receipts.\n"
                "application/: tagged application source, including build recipes and locks.\n"
                "libraries/: matching Qt/PySide/Shiboken upstream source archives.\n"
                "notices/: original Windows/Linux notice ZIPs; each contains REBUILDING.md.\n"
                "Keep this archive available with redistributions of the application.\n"
            ),
        )
        for name, destination in sorted(contents.items()):
            bundle.write(inputs / name, destination)
        bundle.writestr(
            "CONTENTS-SHA256SUMS",
            "".join(
                f"{digest(inputs / name)}  {destination}\n"
                for name, destination in sorted(contents.items())
            ),
        )
    write_checksums(output)
    expected = PUBLIC_ASSETS | ({appimage, "LINUX_INSTALL.md"} if has_appimage else set())
    if {p.name for p in output.iterdir()} != expected:
        raise ValueError("Unexpected files in the final public release output.")
    return output / SUPPORT_ARCHIVE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--build", type=Path, required=True)
    stage.add_argument("--rid", choices=EXECUTABLES, required=True)
    stage.add_argument("--output", type=Path, required=True)
    stage.add_argument("--include-qt-sources", action="store_true")
    checksum = commands.add_parser("checksums")
    checksum.add_argument("directory", type=Path)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--require-appimage", action="store_true")
    assemble.add_argument("--input", type=Path, required=True)
    assemble.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "stage":
        print(stage_release(args.build, args.rid, args.output, args.include_qt_sources))
    elif args.command == "assemble":
        print(assemble_release(args.input, args.output, args.require_appimage))
    else:
        write_checksums(args.directory)


if __name__ == "__main__":
    main()
