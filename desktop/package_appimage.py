"""Add an AppImage around the verified portable binary; never publishes or installs."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "CollectionsStudio-linux-x64.AppImage"
SUPPORT = "CollectionsStudio-AppImage-support.zip"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(entry, cache):
    path = cache / entry.get("name", "appimagetool.AppImage")
    if path.exists():
        if digest(path) != entry["sha256"]:
            raise ValueError(f"Cached AppImage ingredient changed: {path.name}")
        return path
    with urllib.request.urlopen(entry["url"], timeout=60) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"AppImage ingredient failed checksum verification: {path.name}")
    with path.open("xb") as stream:
        stream.write(data)
    return path


def create_appdir(binary, directory):
    (directory / "usr/bin").mkdir(parents=True)
    shutil.copy2(binary, directory / "usr/bin/CollectionsStudio")
    (directory / "usr/bin/CollectionsStudio").chmod(0o755)
    (directory / "AppRun").write_text(
        "#!/bin/sh\nset -eu\n"
        'here="${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"\n'
        "export COLLECTIONS_STUDIO_APPIMAGE=1\n"
        'exec "$here/usr/bin/CollectionsStudio" "$@"\n',
        encoding="utf-8",
    )
    (directory / "AppRun").chmod(0o755)
    (directory / "CollectionsStudio.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Collections Studio\n"
        "Exec=CollectionsStudio\nIcon=CollectionsStudio\nCategories=Game;Utility;\nTerminal=false\n",
        encoding="utf-8",
    )
    (directory / "CollectionsStudio.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
        '<rect width="128" height="128" rx="24" fill="#211d29"/>'
        '<path d="M24 42 64 22l40 20-40 20zm0 22 40 20 40-20M24 86l40 20 40-20" '
        'fill="none" stroke="#bba1e8" stroke-width="8" stroke-linejoin="round"/></svg>',
        encoding="utf-8",
    )


def package(inputs, cache):
    inputs, cache = Path(inputs), Path(cache)
    binary = inputs / "CollectionsStudio-linux-x64"
    with zipfile.ZipFile(inputs / "CollectionsStudio-linux-x64-notices.zip") as notices:
        hashes = json.loads(notices.read("bundle-sha256.json"))
        report = json.loads(notices.read("packaged-self-test.json"))
    if hashes.get("CollectionsStudio") != digest(binary) or not report.get("Frozen"):
        raise ValueError("AppImage requires the exact verified portable build.")
    if any((inputs / name).exists() for name in (IMAGE, SUPPORT)):
        raise ValueError("Refusing to overwrite earlier AppImage outputs.")
    lock = json.loads((ROOT / "desktop/appimage.lock.json").read_text())
    cache.mkdir(parents=True, exist_ok=True)
    tool = fetch(lock["tool"], cache)
    tool.chmod(0o755)
    sources = [(entry, fetch(entry, cache)) for entry in lock["sources"]]
    with tempfile.TemporaryDirectory(prefix="studio-appimage-", dir=cache) as tmp:
        work = Path(tmp)
        appdir = work / "CollectionsStudio.AppDir"
        create_appdir(binary, appdir)
        docs = appdir / "usr/share/doc/CollectionsStudio-AppImage"
        docs.mkdir(parents=True)
        for entry, source in sources:
            found_notice = False
            with tarfile.open(source) as archive:
                for filename in entry["notices"]:
                    member = next(
                        (
                            m
                            for m in archive.getmembers()
                            if m.name.count("/") == 1 and m.name.endswith("/" + filename)
                        ),
                        None,
                    )
                    if member is not None and member.isfile():
                        found_notice = True
                        (docs / (entry["name"] + "-" + filename)).write_bytes(
                            archive.extractfile(member).read()
                        )
            if not found_notice:
                raise ValueError(f"Missing runtime licence in {source.name}")
        runtime = work / "runtime"
        with tool.open("rb") as stream:
            runtime.write_bytes(stream.read(lock["tool"]["runtime_offset"]))
        image = work / IMAGE
        environment = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
        subprocess.run(
            [
                str(tool),
                "--appimage-extract-and-run",
                "--runtime-file",
                str(runtime),
                str(appdir),
                str(image),
            ],
            env=environment,
            check=True,
            timeout=300,
        )
        image.chmod(0o755)
        profile = work / "profile"
        profile.mkdir()
        environment.update(
            QT_QPA_PLATFORM="offscreen",
            XDG_CONFIG_HOME=str(profile / "config"),
            XDG_CACHE_HOME=str(profile / "cache"),
            XDG_DATA_HOME=str(profile / "data"),
        )
        proof = work / "self-test.json"
        subprocess.run(
            [str(image), "--self-test", "--report", str(proof)],
            cwd=profile,
            env=environment,
            check=True,
            timeout=300,
        )
        tested = json.loads(proof.read_text())
        if not tested.get("Frozen") or not tested.get("CreditsAndLicenceDocuments"):
            raise ValueError("The actual AppImage did not pass its packaged self-test.")
        support = work / SUPPORT
        with zipfile.ZipFile(support, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for _, source in sources:
                archive.write(source, "sources/" + source.name)
            for path in docs.iterdir():
                archive.write(path, "notices/" + path.name)
            for name in ("AppRun", "CollectionsStudio.desktop", "CollectionsStudio.svg"):
                archive.write(appdir / name, "AppDir/" + name)
            archive.write(ROOT / "desktop/appimage.lock.json", "appimage.lock.json")
            archive.write(ROOT / "docs/linux-install.md", "LINUX_INSTALL.md")
            archive.write(proof, "packaged-self-test.json")
            archive.writestr(
                "build.json",
                json.dumps(
                    {
                        "ImageSha256": digest(image),
                        "PayloadSha256": digest(binary),
                        "RuntimeSource": lock["tool"]["runtime_commit"],
                    }
                ),
            )
        shutil.copy2(image, inputs / IMAGE)
        shutil.copy2(support, inputs / SUPPORT)
    return inputs / IMAGE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.input, args.cache))


if __name__ == "__main__":
    main()
