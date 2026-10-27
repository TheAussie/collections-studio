"""Collect installed distribution licenses and the pinned helper's dependency notices."""

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = {
    "CPython-3.12.14-LICENSE.txt": "https://raw.githubusercontent.com/python/cpython/v3.12.14/LICENSE",
    "dotnet-8.0.31-LICENSE.txt": "https://raw.githubusercontent.com/dotnet/runtime/v8.0.31/LICENSE.TXT",
    "dotnet-8.0.31-THIRD-PARTY-NOTICES.txt": "https://raw.githubusercontent.com/dotnet/runtime/v8.0.31/THIRD-PARTY-NOTICES.TXT",
    "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
}
QT_SOURCES = {
    "qtbase": "https://codeload.github.com/qt/qtbase/tar.gz/refs/tags/v6.12.0",
    "qtsvg": "https://codeload.github.com/qt/qtsvg/tar.gz/refs/tags/v6.12.0",
    "qtwayland": "https://codeload.github.com/qt/qtwayland/tar.gz/refs/tags/v6.12.0",
    "pyside-setup": "https://codeload.github.com/pyside/pyside-setup/tar.gz/refs/tags/v6.12.0",
}


def collect_qt_sources(destination):
    sources = destination.parent / "corresponding-sources"
    sources.mkdir()
    locked = {
        entry["Module"]: entry
        for entry in json.loads(
            (ROOT / "desktop" / "qt-sources.lock.json").read_text(encoding="utf-8")
        )
    }

    def fetch(entry):
        name, url = entry
        archive = sources / f"{name}-6.12.0.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("xb") as stream:
            shutil.copyfileobj(response, stream)
        with archive.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if locked[name]["Url"] != url or locked[name]["Sha256"] != checksum:
            raise ValueError("An upstream source archive differs from the reviewed source lock.")
        with tarfile.open(archive) as source:
            for member in source:
                path = Path(member.name)
                if not member.isfile() or path.is_absolute() or ".." in path.parts:
                    continue
                if (
                    any(part.lower() in ("licenses", "license") for part in path.parts)
                    or path.name.lower().startswith(("license", "copying", "copyright", "notice"))
                    or path.name == "qt_attribution.json"
                ):
                    if member.size > 4 * 1024 * 1024:
                        raise ValueError("An upstream notice exceeds 4 MiB.")
                    output = destination / "Qt-source-notices" / name / path
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as stream:
                        output.write_bytes(stream.read())
        return {
            "Module": name,
            "Version": "6.12.0",
            "Url": url,
            "Sha256": checksum,
            "Archive": archive.name,
        }

    with ThreadPoolExecutor(max_workers=4) as workers:
        return list(workers.map(fetch, QT_SOURCES.items()))


def copy_project_documents(destination):
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for source in (
        ROOT / "LICENSE",
        ROOT / "CREDITS.md",
        ROOT / "desktop" / "THIRD_PARTY_NOTICES.md",
    ):
        target = destination / source.name
        shutil.copy2(source, target)
        records.append(
            {"File": source.name, "Sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        )
    return records


def collect(destination, rid):
    destination.mkdir(parents=True)
    project_documents = copy_project_documents(destination)
    manifest = {
        "FirstPartyLicense": "MIT",
        "ProjectDocuments": project_documents,
        "PythonPackages": [],
        "NugetPackages": [],
        "SourceLicenseUrls": COMMON,
    }
    for name in (
        "PySide6-Essentials",
        "shiboken6",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "altgraph",
        "packaging",
        "setuptools",
        "pefile",
        "pywin32-ctypes",
    ):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        target = destination / name
        target.mkdir()
        (target / "METADATA.txt").write_text(
            distribution.read_text("METADATA") or "", encoding="utf-8"
        )
        copied = []
        for file in distribution.files or []:
            if any(
                part.lower() in ("licenses", "license") for part in file.parts
            ) or file.name.lower().startswith(("license", "copying", "notice")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    output = target.joinpath(*file.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, output)
                    copied.append(str(file))
        manifest["PythonPackages"].append(
            {"Name": name, "Version": distribution.version, "LicenseFiles": copied}
        )
    for filename, url in COMMON.items():
        with urllib.request.urlopen(url, timeout=30) as response:
            (destination / filename).write_bytes(response.read(4 * 1024 * 1024))
    # The installed 6.12 wheels omit license files; preserve matching upstream trees too.
    manifest["QtCorrespondingSources"] = collect_qt_sources(destination)
    manifest["NugetPackages"] = collect_nuget_notices(destination, rid)
    (destination / "dependency-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def collect_nuget_notices(destination, rid):
    location = subprocess.check_output(
        ["dotnet", "nuget", "locals", "global-packages", "--list"], text=True
    )
    packages_root = Path(location.strip().split(": ", 1)[1])
    lock = json.loads((ROOT / "desktop" / f"realm-{rid}.lock.json").read_text(encoding="utf-8"))
    seen = set()
    records = []
    for packages in lock["dependencies"].values():
        for name, package in packages.items():
            key = (name, package["resolved"])
            if key in seen:
                continue
            seen.add(key)
            folder = packages_root / name.lower() / package["resolved"]
            nuspec = next(folder.glob("*.nuspec"))
            metadata = list(ET.parse(nuspec).getroot())[0]
            fields = {entry.tag.split("}")[-1]: entry.text for entry in metadata}
            target = destination / "nuget" / name
            target.mkdir(parents=True)
            # A long package ID repeated as the nuspec filename exceeds Windows
            # MAX_PATH in an otherwise ordinary build folder. Keep the package
            # directory/identity and exact metadata bytes, with a short filename.
            output = target / "package.nuspec"
            shutil.copy2(nuspec, output)
            copied = []
            for file in folder.iterdir():
                if file.is_file() and file.name.lower().startswith(
                    ("license", "notice", "third-party")
                ):
                    shutil.copy2(file, target / file.name)
                    copied.append((target / file.name).relative_to(destination).as_posix())
            records.append(
                {
                    "Name": name,
                    "Version": package["resolved"],
                    "License": fields.get("license") or fields.get("licenseUrl"),
                    "ProjectUrl": fields.get("projectUrl"),
                    "Copyright": fields.get("copyright"),
                    "Nuspec": output.relative_to(destination).as_posix(),
                    "LicenseFiles": sorted(copied),
                }
            )
    return records
