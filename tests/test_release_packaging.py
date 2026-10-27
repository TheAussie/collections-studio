import hashlib
import json
import zipfile

import pytest

from desktop import package_release


@pytest.fixture
def verified_build(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "desktop").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "docs/releases.md").write_text("Rebuild instructions", encoding="utf-8")
    archive = b"Exact upstream source fixture"
    checksum = hashlib.sha256(archive).hexdigest()
    entries = [{"Module": "qtbase", "Archive": "qtbase.tar.gz", "Sha256": checksum}]
    (root / "desktop/qt-sources.lock.json").write_text(json.dumps(entries))
    monkeypatch.setattr(package_release, "ROOT", root)
    build = tmp_path / "build"
    (build / "dist").mkdir(parents=True)
    (build / "notices").mkdir()
    (build / "corresponding-sources").mkdir()
    (build / "corresponding-sources/qtbase.tar.gz").write_bytes(archive)
    for filename in ["LICENSE", "CREDITS.md", "THIRD_PARTY_NOTICES.md"]:
        (build / "notices" / filename).write_text("Exact " + filename, encoding="utf-8")
    (build / "notices/dependency-manifest.json").write_text(
        json.dumps({"FirstPartyLicense": "MIT", "QtCorrespondingSources": entries})
    )
    (build / "packaged-self-test.json").write_text(
        json.dumps({"Frozen": True, "CreditsAndLicenceDocuments": True})
    )
    for rid, (binary_name, _) in package_release.EXECUTABLES.items():
        (build / "dist" / binary_name).write_bytes(("Binary " + rid).encode())
    hashes = {
        name: package_release.digest(build / "dist" / name)
        for name, _ in package_release.EXECUTABLES.values()
    }
    (build / "bundle-sha256.json").write_text(json.dumps(hashes))
    (build / "build-info.json").write_text(
        json.dumps({"Format": "onefile", "RuntimeIdentifier": "linux-x64"})
    )
    return build


@pytest.mark.parametrize("rid", ["win-x64", "linux-x64"])
def test_stages_one_native_binary_with_complete_separate_notices_and_exact_sources(
    verified_build, tmp_path, rid
):
    build = verified_build
    (build / "build-info.json").write_text(
        json.dumps({"Format": "onefile", "RuntimeIdentifier": rid})
    )
    output = tmp_path / "release"
    binary = package_release.stage_release(build, rid, output, include_qt_sources=True)
    original, expected = package_release.EXECUTABLES[rid]
    assert (
        binary.name == expected and binary.read_bytes() == (build / "dist" / original).read_bytes()
    )
    assert not any(path.is_dir() for path in output.iterdir())
    with zipfile.ZipFile(output / f"CollectionsStudio-{rid}-notices.zip") as archive:
        assert archive.read("notices/LICENSE") == b"Exact LICENSE"
        assert archive.read("notices/CREDITS.md") == b"Exact CREDITS.md"
        assert "REBUILDING.md" in archive.namelist()
        assert json.loads(archive.read("packaged-self-test.json"))["Frozen"]
    assert (output / "qtbase.tar.gz").read_bytes() == b"Exact upstream source fixture"
    package_release.write_checksums(output)
    lines = (output / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        checksum, name = line.split("  ", 1)
        assert checksum == package_release.digest(output / name)
    package_release.write_checksums(output)
    assert (output / "SHA256SUMS").read_text().splitlines() == lines


@pytest.mark.parametrize(
    "failure", ["unfrozen", "missing_credits", "binary_changed", "sources_changed", "onedir"]
)
def test_refuses_unverified_release_before_creating_assets(verified_build, tmp_path, failure):
    build = verified_build
    if failure == "unfrozen":
        (build / "packaged-self-test.json").write_text(json.dumps({"Frozen": False}))
    elif failure == "missing_credits":
        (build / "notices/CREDITS.md").unlink()
    elif failure == "binary_changed":
        (build / "dist/CollectionsStudio").write_bytes(b"Not the tested binary")
    elif failure == "sources_changed":
        (build / "corresponding-sources/qtbase.tar.gz").write_bytes(b"Changed source")
    else:
        (build / "build-info.json").write_text(
            json.dumps({"Format": "onedir", "RuntimeIdentifier": "linux-x64"})
        )
    output = tmp_path / "release"
    with pytest.raises(ValueError):
        package_release.stage_release(build, "linux-x64", output)
    assert not output.exists()
