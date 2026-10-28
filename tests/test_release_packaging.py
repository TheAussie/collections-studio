import hashlib
import io
import json
import shutil
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
        signature = b"MZ" if rid == "win-x64" else b"\x7fELF"
        (build / "dist" / binary_name).write_bytes(signature + ("Binary " + rid).encode())
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


@pytest.mark.parametrize("failure", [None, "missing", "wrong_binary", "wrong_version", "failed"])
def test_versioned_release_requires_matching_native_update_rehearsal(
    verified_build, tmp_path, failure
):
    build = verified_build
    info = json.loads((build / "build-info.json").read_text())
    info.update(ApplicationVersion="0.1.1", NativeUpdateRehearsal=True)
    (build / "build-info.json").write_text(json.dumps(info))
    (build / "packaged-self-test.json").write_text(
        json.dumps(
            {
                "Frozen": True,
                "CreditsAndLicenceDocuments": True,
                "VersionedUpdateDownloadAndReplacement": True,
            }
        )
    )
    rehearsal = build / "update-rehearsal/native-update-rehearsal.json"
    if failure != "missing":
        rehearsal.parent.mkdir()
        rehearsal.write_text(
            json.dumps(
                {
                    "Passed": failure != "failed",
                    "Version": "9.9.9" if failure == "wrong_version" else "0.1.1",
                    "BinarySha256": "0" * 64
                    if failure == "wrong_binary"
                    else package_release.digest(build / "dist/CollectionsStudio"),
                }
            )
        )
    output = tmp_path / "release"
    if failure:
        with pytest.raises(ValueError, match="native update rehearsal"):
            package_release.stage_release(build, "linux-x64", output)
        assert not output.exists()
    else:
        package_release.stage_release(build, "linux-x64", output)
        with zipfile.ZipFile(output / "CollectionsStudio-linux-x64-notices.zip") as archive:
            assert archive.read("native-update-rehearsal.json") == rehearsal.read_bytes()


@pytest.fixture
def release_inputs(verified_build, tmp_path):
    build, inputs = verified_build, tmp_path / "inputs"
    inputs.mkdir()
    for rid in package_release.EXECUTABLES:
        (build / "build-info.json").write_text(
            json.dumps(
                {
                    "Format": "onefile",
                    "RuntimeIdentifier": rid,
                }
            )
        )
        staged = tmp_path / ("staged-" + rid)
        package_release.stage_release(build, rid, staged, include_qt_sources=rid == "linux-x64")
        for path in staged.iterdir():
            shutil.copy2(path, inputs / path.name)
    (inputs / "CollectionsStudio-source.tar.gz").write_bytes(
        b"Exact tagged application source fixture"
    )
    return inputs


def test_final_release_has_four_files_and_preserves_every_supporting_archive(
    release_inputs, tmp_path
):
    output = tmp_path / "public"
    before = {p.name: p.read_bytes() for p in release_inputs.iterdir()}
    support = package_release.assemble_release(release_inputs, output)
    assert {p.name for p in output.iterdir()} == package_release.PUBLIC_ASSETS
    assert support.name == "CollectionsStudio-sources-and-notices.zip"
    assert {p.name: p.read_bytes() for p in release_inputs.iterdir()} == before
    with zipfile.ZipFile(support) as bundle:
        sources = {
            "application/CollectionsStudio-source.tar.gz": "CollectionsStudio-source.tar.gz",
            "libraries/qtbase.tar.gz": "qtbase.tar.gz",
        }
        for rid in package_release.EXECUTABLES:
            name = f"CollectionsStudio-{rid}-notices.zip"
            sources["notices/" + name] = name
        assert set(bundle.namelist()) == set(sources) | {"README.txt", "CONTENTS-SHA256SUMS"}
        manifest = dict(
            line.split("  ", 1)[::-1]
            for line in bundle.read("CONTENTS-SHA256SUMS").decode().splitlines()
        )
        for name, original in sources.items():
            assert bundle.read(name) == before[original]
            assert manifest[name] == hashlib.sha256(before[original]).hexdigest()
    sums = dict(
        line.split("  ", 1)[::-1] for line in (output / "SHA256SUMS").read_text().splitlines()
    )
    assert set(sums) == package_release.PUBLIC_ASSETS - {"SHA256SUMS"}
    for name, checksum in sums.items():
        assert checksum == package_release.digest(output / name)


@pytest.mark.parametrize(
    "failure", ["missing", "extra", "source_changed", "binary_changed", "wrong_platform"]
)
def test_assembly_rejects_missing_extra_or_changed_inputs_before_creating_public_files(
    release_inputs, tmp_path, failure
):
    if failure == "missing":
        (release_inputs / "CollectionsStudio-win-x64-notices.zip").unlink()
    elif failure == "extra":
        (release_inputs / "unrelated-file.txt").write_text("must not be published")
    elif failure == "source_changed":
        (release_inputs / "qtbase.tar.gz").write_bytes(b"Changed upstream source")
    elif failure == "binary_changed":
        (release_inputs / "CollectionsStudio-windows-x64.exe").write_bytes(b"Changed binary")
    else:
        (release_inputs / "CollectionsStudio-win-x64-notices.zip").write_bytes(
            (release_inputs / "CollectionsStudio-linux-x64-notices.zip").read_bytes()
        )
    output = tmp_path / "public"
    with pytest.raises(ValueError):
        package_release.assemble_release(release_inputs, output)
    assert not output.exists()


def test_assembly_will_not_overwrite_an_existing_output(release_inputs, tmp_path):
    output = tmp_path / "public"
    output.mkdir()
    keep = output / "existing.txt"
    keep.write_bytes(b"Keep this")
    with pytest.raises(ValueError, match="unused"):
        package_release.assemble_release(release_inputs, output)
    assert keep.read_bytes() == b"Keep this"


@pytest.mark.parametrize("failure", [None, "mixed_versions", "proof_binary", "proof_failed"])
def test_final_assembly_rechecks_native_receipts_and_matching_versions(
    release_inputs, tmp_path, failure
):
    for rid, (_, binary) in package_release.EXECUTABLES.items():
        path = release_inputs / f"CollectionsStudio-{rid}-notices.zip"
        with zipfile.ZipFile(path) as bundle:
            entries = {name: bundle.read(name) for name in bundle.namelist()}
        version = "0.1.3" if failure == "mixed_versions" and rid == "win-x64" else "0.1.2"
        info = json.loads(entries["build-info.json"])
        info.update(ApplicationVersion=version, NativeUpdateRehearsal=True)
        report = json.loads(entries["packaged-self-test.json"])
        report["VersionedUpdateDownloadAndReplacement"] = True
        entries["build-info.json"] = json.dumps(info).encode()
        entries["packaged-self-test.json"] = json.dumps(report).encode()
        entries["native-update-rehearsal.json"] = json.dumps(
            {
                "Version": version,
                "Passed": failure != "proof_failed",
                "BinarySha256": "0" * 64
                if failure == "proof_binary"
                else package_release.digest(release_inputs / binary),
            }
        ).encode()
        with zipfile.ZipFile(path, "w") as bundle:
            for name, contents in entries.items():
                bundle.writestr(name, contents)
    output = tmp_path / "public"
    if failure:
        with pytest.raises(ValueError):
            package_release.assemble_release(release_inputs, output)
        assert not output.exists()
    else:
        package_release.assemble_release(release_inputs, output)
        with zipfile.ZipFile(output / package_release.SUPPORT_ARCHIVE) as combined:
            with zipfile.ZipFile(
                io.BytesIO(combined.read("notices/CollectionsStudio-win-x64-notices.zip"))
            ) as notices:
                assert json.loads(notices.read("native-update-rehearsal.json"))["Passed"]


@pytest.mark.parametrize("system", ["linux", "win32"])
def test_four_file_release_still_supports_verified_updater_downloads(
    release_inputs, tmp_path, system
):
    from tools.app_updates import API, REPOSITORY, check_for_update, download_update

    output = tmp_path / "public"
    package_release.assemble_release(release_inputs, output)
    payloads, assets = {}, []
    for path in output.iterdir():
        url = f"https://github.com/{REPOSITORY}/releases/download/v0.1.2/{path.name}"
        payloads[url] = path.read_bytes()
        assets.append(
            {
                "name": path.name,
                "state": "uploaded",
                "size": path.stat().st_size,
                "digest": "sha256:" + package_release.digest(path),
                "browser_download_url": url,
            }
        )
    payloads[API] = json.dumps({"tag_name": "v0.1.2", "assets": assets}).encode()

    class Transport:
        def open(self, url):
            return io.BytesIO(payloads[url])

    info = check_for_update("0.1.1", client=Transport(), system=system, machine="x86_64")
    download = tmp_path / "download"
    download.mkdir()
    checksum = download_update(info, download, client=Transport())
    assert checksum == package_release.digest(output / info.asset_name)
    assert (download / "download").read_bytes() == (output / info.asset_name).read_bytes()
