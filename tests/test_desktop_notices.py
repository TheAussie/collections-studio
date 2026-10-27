import json
from pathlib import PureWindowsPath

from desktop import collect_notices


def test_long_nuget_metadata_path_fits_the_reported_windows_build_and_preserves_notices(
    tmp_path, monkeypatch
):
    # The original package-ID + package-ID.nuspec layout was exactly MAX_PATH
    # (260 characters) in the user's Windows source/output folder.
    name = "runtime.debian.8-x64.runtime.native.System.Security.Cryptography.OpenSsl"
    version = "4.3.2"
    cache = tmp_path / "nuget cache"
    package = cache / name.lower() / version
    package.mkdir(parents=True)
    nuspec = package / (name.lower() + ".nuspec")
    metadata = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">'
        f"<metadata><id>{name}</id><version>{version}</version>"
        '<license type="expression">MIT</license><copyright>Original ©</copyright>'
        "<projectUrl>https://example.test/</projectUrl></metadata></package>"
    ).encode()
    nuspec.write_bytes(metadata)
    licenses = {
        "LICENSE.txt": b"Exact original license\r\n",
        "THIRD-PARTY-NOTICES.txt": b"Exact original third-party notices\n",
    }
    for filename, content in licenses.items():
        (package / filename).write_bytes(content)
    root = tmp_path / "project"
    (root / "desktop").mkdir(parents=True)
    lock = {"dependencies": {"net8.0": {name: {"resolved": version}}}}
    # A package can occur in more than one target; retain one exact notice copy.
    lock["dependencies"]["net8.0/win-x64"] = lock["dependencies"]["net8.0"]
    (root / "desktop" / "realm-win-x64.lock.json").write_text(json.dumps(lock))
    monkeypatch.setattr(collect_notices, "ROOT", root)
    monkeypatch.setattr(
        collect_notices.subprocess,
        "check_output",
        lambda *_args, **_kwargs: f"global-packages: {cache}\n",
    )
    destination = tmp_path / "notices"
    records = collect_notices.collect_nuget_notices(destination, "win-x64")
    assert len(records) == 1
    record = records[0]
    assert record["Name"] == name and record["Version"] == version
    assert record["License"] == "MIT" and record["Copyright"] == "Original ©"
    assert record["ProjectUrl"] == "https://example.test/"
    assert (destination / record["Nuspec"]).read_bytes() == metadata
    assert {path.rsplit("/", 1)[-1] for path in record["LicenseFiles"]} == licenses.keys()
    for relative in record["LicenseFiles"]:
        assert (destination / relative).read_bytes() == licenses[relative.rsplit("/", 1)[-1]]
    windows = PureWindowsPath(
        r"C:\Projects\CollectionsStudio-source\artifacts\windows-build\dist"
        r"\CollectionsStudio\_internal\notices"
    )
    assert len(str(windows / "nuget" / name / nuspec.name)) == 260
    for file in destination.rglob("*"):
        if file.is_file():
            assert len(str(windows / file.relative_to(destination))) < 240


def test_project_documents_preserve_exact_bytes_in_both_bundle_locations(tmp_path, monkeypatch):
    import hashlib

    root = tmp_path / "source"
    (root / "desktop").mkdir(parents=True)
    originals = {
        "LICENSE": b"MIT License\nCopyright Test\n",
        "CREDITS.md": "# Credits\nThanks 練習\n".encode(),
        "THIRD_PARTY_NOTICES.md": b"# Third-party notices\n",
    }
    for name, content in originals.items():
        path = root / ("desktop" if name == "THIRD_PARTY_NOTICES.md" else "") / name
        path.write_bytes(content)
    monkeypatch.setattr(collect_notices, "ROOT", root)
    for destination in (tmp_path / "bundle", tmp_path / "bundle/_internal/notices"):
        records = collect_notices.copy_project_documents(destination)
        assert {record["File"] for record in records} == originals.keys()
        for record in records:
            assert (destination / record["File"]).read_bytes() == originals[record["File"]]
            assert record["Sha256"] == hashlib.sha256(originals[record["File"]]).hexdigest()
