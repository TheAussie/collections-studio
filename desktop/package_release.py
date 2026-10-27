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
    if digest(binary) != hashes[source_name]:
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
    args = parser.parse_args()
    if args.command == "stage":
        print(stage_release(args.build, args.rid, args.output, args.include_qt_sources))
    else:
        write_checksums(args.directory)


if __name__ == "__main__":
    main()
