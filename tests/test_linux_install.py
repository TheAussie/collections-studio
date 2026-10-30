import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tools import linux_install as installer
from tools.beatmap_downloads import Cancelled
from tools.collection_save import database_save_lock

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Per-user Linux integration")


@pytest.fixture
def setup(tmp_path):
    data = tmp_path / "user data %f $quote"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    source = tmp_path / "download"
    source.write_bytes(b"\x7fELF synthetic portable app")
    source.chmod(0o755)
    return installer.Layout(data, desktop), installer.Artifact(source, "binary")


@pytest.mark.parametrize("kind", ["binary", "appimage"])
def test_install_reinstall_and_uninstall_preserve_original_and_user_data(setup, kind):
    layout, artifact = setup
    artifact = installer.Artifact(artifact.path, kind)
    layout.data.mkdir(parents=True)
    protected = layout.data / "collection.db"
    protected.write_bytes(b"User collection")
    downloads = layout.data / "collections-studio/downloads/report.json"
    downloads.parent.mkdir(parents=True)
    downloads.write_text("Saved queue")
    result = installer.install(layout, artifact, "0.1.5", desktop=True)
    assert result["path"] == str(layout.binary) and not result["backup"]
    assert layout.binary.read_bytes() == artifact.path.read_bytes()
    assert layout.icon.read_bytes() == installer.icon_path().read_bytes()
    assert layout.launcher.read_bytes() == layout.desktop.read_bytes()
    assert "--manage-installation" in layout.launcher.read_text()
    assert installer.installation(layout)["kind"] == kind
    assert layout.binary.stat().st_mode & 0o111
    installer.install(layout, artifact, "0.1.5", desktop=True)
    installer.install(layout, installer.Artifact(layout.binary, kind), "0.1.5", desktop=True)
    # A successful standalone auto-update is still an owned installed executable.
    layout.binary.write_bytes(b"\x7fELF verified newer portable version")
    removed = installer.uninstall(layout)
    assert str(layout.binary) in removed["removed"] and not removed["kept"]
    for path in (layout.binary, layout.manifest, layout.icon, layout.launcher, layout.desktop):
        assert not path.exists()
    assert artifact.path.read_bytes() == b"\x7fELF synthetic portable app"
    assert protected.read_bytes() == b"User collection" and downloads.read_text() == "Saved queue"
    assert installer.uninstall(layout)["removed"] == []


def test_existing_manual_launcher_is_backed_up_and_modified_shortcut_is_kept(setup):
    layout, artifact = setup
    layout.launcher.parent.mkdir(parents=True)
    layout.launcher.write_text("Old manually created launcher")
    result = installer.install(layout, artifact, "0.1.5", desktop=True)
    copies = Path(result["backup"])
    assert any(p.read_bytes() == b"Old manually created launcher" for p in copies.iterdir())
    layout.desktop.write_text("Customized shortcut")
    removed = installer.uninstall(layout)
    assert str(layout.desktop) in removed["kept"]
    assert layout.desktop.read_text() == "Customized shortcut"
    assert copies.is_dir()


def test_switching_format_reuses_one_installed_file_and_launcher(setup):
    layout, artifact = setup
    installer.install(layout, artifact, "0.1.5")
    image = artifact.path.with_suffix(".AppImage")
    image.write_bytes(b"\x7fELF AI type2 fake image")
    installer.install(layout, installer.Artifact(image, "appimage"), "0.1.6")
    assert layout.binary.read_bytes() == image.read_bytes()
    assert installer.installation(layout)["kind"] == "appimage"
    assert len(list(layout.launcher.parent.glob("*.desktop"))) == 1


@pytest.mark.parametrize("role", ["binary", "icon", "launcher", "manifest"])
def test_symlink_destinations_never_change_external_files(setup, tmp_path, role):
    layout, artifact = setup
    target = {**layout.roles(), "manifest": layout.manifest}[role]
    target.parent.mkdir(parents=True, exist_ok=True)
    protected = tmp_path / "real collection.db"
    protected.write_bytes(b"Do not touch")
    target.symlink_to(protected)
    with pytest.raises(installer.InstallError):
        installer.install(layout, artifact, "0.1.5")
    assert protected.read_bytes() == b"Do not touch" and target.is_symlink()


def test_unmanaged_binary_and_forged_manifest_are_not_overwritten_or_removed(setup, tmp_path):
    layout, artifact = setup
    layout.root.mkdir(parents=True)
    layout.binary.write_bytes(b"Do not overwrite")
    with pytest.raises(installer.InstallError, match="unmanaged"):
        installer.install(layout, artifact, "0.1.5")
    assert layout.binary.read_bytes() == b"Do not overwrite"
    layout.binary.unlink()
    installer.install(layout, artifact, "0.1.5")
    record = json.loads(layout.manifest.read_text())
    external = tmp_path / "data.db"
    external.write_text("Untouched")
    record["files"]["binary"]["path"] = str(external)
    layout.manifest.write_text(json.dumps(record))
    with pytest.raises(installer.InstallError):
        installer.uninstall(layout)
    assert external.read_text() == "Untouched" and layout.binary.exists()


def test_failed_publish_rolls_back_previous_installation_exactly(setup, monkeypatch):
    layout, artifact = setup
    installer.install(layout, artifact, "0.1.5", desktop=True)
    before = {p: p.read_bytes() for p in [*layout.roles().values(), layout.manifest]}
    artifact.path.write_bytes(b"\x7fELF new version")
    replace = installer.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if target == layout.launcher and not failed:
            failed = True
            raise OSError("Simulated disk failure")
        return replace(source, target)

    monkeypatch.setattr(installer.os, "replace", fail_once)
    with pytest.raises(OSError, match="disk failure"):
        installer.install(layout, artifact, "0.1.6", desktop=True)
    assert {p: p.read_bytes() for p in before} == before


def test_cancel_and_existing_updater_lock_do_not_modify_installation(setup):
    layout, artifact = setup
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        installer.install(layout, artifact, "0.1.5", stop=stop)
    assert not layout.data.exists()
    installer.install(layout, artifact, "0.1.5")
    before = layout.binary.read_bytes()
    with database_save_lock(layout.binary, realm=False):
        with pytest.raises(installer.InstallError):
            installer.uninstall(layout)
    assert layout.binary.read_bytes() == before


def test_source_and_extracted_payloads_cannot_be_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(installer.sys, "frozen", False, raising=False)
    with pytest.raises(installer.InstallError, match="Source checkouts"):
        installer.running_artifact()
    monkeypatch.setattr(installer.sys, "frozen", True, raising=False)
    monkeypatch.setattr(installer.sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "app-version.json").write_text('{"format":"onefile"}')
    monkeypatch.setenv("COLLECTIONS_STUDIO_APPIMAGE", "1")
    monkeypatch.delenv("APPIMAGE", raising=False)
    with pytest.raises(installer.InstallError, match="original AppImage"):
        installer.running_artifact()
    image = tmp_path / "outer.AppImage"
    image.write_bytes(b"\x7fELF")
    monkeypatch.setenv("APPIMAGE", str(image))
    assert installer.running_artifact() == installer.Artifact(image, "appimage")


@pytest.mark.skipif(
    not shutil.which("desktop-file-validate"), reason="Optional native desktop validator"
)
def test_generated_entry_passes_native_validator_with_escaped_paths(setup):
    layout, artifact = setup
    installer.install(layout, artifact, "0.1.5")
    subprocess.run(["desktop-file-validate", str(layout.launcher)], check=True, capture_output=True)


def test_relative_xdg_path_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    monkeypatch.setattr(installer.Path, "home", lambda: tmp_path)
    assert installer.user_layout().data == tmp_path / ".local/share"


def test_newer_concurrent_edit_is_not_overwritten_during_rollback(setup, monkeypatch):
    layout, artifact = setup
    installer.install(layout, artifact, "0.1.5")
    original = layout.binary.read_bytes()
    artifact.path.write_bytes(b"\x7fELF update")
    replace = installer.os.replace

    def conflicting_edit(source, target):
        if target == layout.launcher:
            layout.binary.write_bytes(b"Newer independent edit")
            raise OSError("Simulated conflict")
        return replace(source, target)

    monkeypatch.setattr(installer.os, "replace", conflicting_edit)
    with pytest.raises(installer.InstallError, match="Recovery copies"):
        installer.install(layout, artifact, "0.1.6")
    assert layout.binary.read_bytes() == b"Newer independent edit"
    assert any(
        p.read_bytes() == original
        for p in (layout.data / "collections-studio/installation-backups").rglob("*")
        if p.is_file()
    )


def test_relocated_desktop_shortcut_is_kept_without_following_record_paths(setup, tmp_path):
    layout, artifact = setup
    installer.install(layout, artifact, "0.1.5", desktop=True)
    desktop = tmp_path / "new Desktop"
    desktop.mkdir()
    moved = installer.Layout(layout.data, desktop)
    result = installer.uninstall(moved)
    assert str(layout.desktop) in result["kept"] and layout.desktop.exists()
    assert not layout.binary.exists()


def test_source_replacement_while_staging_is_rejected_before_publish(setup, monkeypatch):
    layout, artifact = setup
    original = installer._copy

    def changed_source(source, destination, stop):
        if source == artifact.path:
            source.write_bytes(b"\x7fELF different download")
        return original(source, destination, stop)

    monkeypatch.setattr(installer, "_copy", changed_source)
    with pytest.raises(installer.InstallError, match="changed"):
        installer.install(layout, artifact, "0.1.5")
    assert (
        not layout.binary.exists() and not layout.launcher.exists() and not layout.manifest.exists()
    )
