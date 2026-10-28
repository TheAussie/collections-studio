import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import update_install as install
from tools.app_updates import UpdateError
from tools.beatmap_downloads import _private_json

OLD, NEW = b"old executable fixture", b"new executable fixture"


@pytest.fixture
def plan(tmp_path):
    target = tmp_path / "Collections Studio.exe"
    target.write_bytes(OLD)
    target.chmod(0o755)
    stage = install.create_stage(target)
    (stage / "download").write_bytes(NEW)
    path = stage / "plan.json"
    _private_json(
        path,
        {
            "format": 1,
            "pid": 123456,
            "target": str(target),
            "old_sha256": install.digest(target),
            "new_sha256": install.digest(stage / "download"),
            "version": "0.1.1",
            "open_file": str(tmp_path / "collection 練習.db"),
        },
    )
    return path, target


def test_wait_then_replace_confirm_and_clean_only_private_staging_files(plan):
    path, target = plan
    order = []

    def wait(pid):
        order.append("wait")
        assert pid == 123456 and target.read_bytes() == OLD

    def launch(arguments):
        order.append("launch")
        assert target.read_bytes() == NEW
        assert arguments == [
            str(target),
            "--finish-update",
            str(path),
            "--file",
            str(target.parent / "collection 練習.db"),
        ]
        assert (path.parent / "previous").read_bytes() == OLD
        install.confirm_startup(path, target, "0.1.1")
        return SimpleNamespace(poll=lambda: None)

    install.apply_update(path, wait_parent=wait, launch=launch)
    assert order == ["wait", "launch"]
    assert install.cleanup_update(path)
    assert target.read_bytes() == NEW and not path.parent.exists()


@pytest.mark.parametrize("failure", ["launch", "startup_exit", "replacement"])
def test_failed_update_restores_original_before_reopening(plan, monkeypatch, failure):
    path, target = plan
    calls = []
    replace = install._replace_wait

    def replacement(source, destination):
        if failure == "replacement" and Path(source).name == "download":
            raise OSError("simulated disk failure")
        return replace(source, destination)

    monkeypatch.setattr(install, "_replace_wait", replacement)

    def launch(arguments):
        calls.append(target.read_bytes())
        if len(calls) == 1 and failure == "launch":
            raise OSError("cannot start")
        return SimpleNamespace(poll=lambda: 1)

    install.apply_update(path, wait_parent=lambda _pid: None, launch=launch)
    assert target.read_bytes() == OLD and calls[-1] == OLD
    assert json.loads((path.parent / "result.json").read_text())["status"] == "failed"
    assert install.confirm_startup(path, target, "0.1.0")["status"] == "failed"


@pytest.mark.parametrize("changed", ["target", "download"])
def test_changed_files_never_get_installed_or_overwritten(plan, changed):
    path, target = plan
    altered = target if changed == "target" else path.parent / "download"
    altered.write_bytes(b"unexpected newer contents")
    with pytest.raises(UpdateError, match="changed"):
        install.apply_update(
            path, wait_parent=lambda _pid: pytest.fail("Must reject before closing")
        )
    assert target.read_bytes() == (b"unexpected newer contents" if changed == "target" else OLD)


def test_parent_timeout_and_aborted_handoff_leave_original_untouched(plan):
    path, target = plan

    def timeout(_pid):
        raise UpdateError("still running")

    with pytest.raises(UpdateError):
        install.apply_update(path, wait_parent=timeout)
    assert target.read_bytes() == OLD
    (path.parent / "abort").touch()
    install.apply_update(path, wait_parent=lambda _pid: None)
    assert target.read_bytes() == OLD and not (path.parent / "previous").exists()


def test_slow_running_new_client_is_not_killed_and_keeps_recovery_copy(plan):
    path, target = plan
    install.apply_update(
        path,
        wait_parent=lambda _pid: None,
        launch=lambda _args: SimpleNamespace(poll=lambda: None),
        confirmation_timeout=0,
    )
    assert target.read_bytes() == NEW and (path.parent / "previous").read_bytes() == OLD
    assert not install.cleanup_update(path)
    install.confirm_startup(path, target, "0.1.1")
    assert install.cleanup_update(path)


def test_startup_version_mismatch_and_path_escape_rejected(plan, tmp_path):
    path, target = plan
    data = json.loads(path.read_text())
    target.write_bytes(NEW)
    _private_json(path.parent / "result.json", {"status": "installed"})
    with pytest.raises(UpdateError, match="verified release"):
        install.confirm_startup(path, target, "0.1.0")
    data["target"] = str(tmp_path.parent / "unrelated.exe")
    _private_json(path, data)
    with pytest.raises(UpdateError, match="folder"):
        install.apply_update(path)


def test_source_python_is_never_a_replacement_target(monkeypatch):
    monkeypatch.setattr(install.sys, "frozen", False, raising=False)
    with pytest.raises(UpdateError, match="Source checkouts"):
        install.portable_target()


def test_other_update_holds_executable_lease_without_closing_client(plan):
    from tools.collection_save import database_save_lock

    path, target = plan
    with database_save_lock(target, realm=False):
        with pytest.raises(PermissionError):
            install.apply_update(
                path, wait_parent=lambda _pid: pytest.fail("Client must stay open")
            )
    assert target.read_bytes() == OLD and not (path.parent / "ready").exists()


def test_restart_resets_pyinstaller_and_old_library_environment(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/old-extraction")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/custom")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/tmp/old-extraction/plugins")
    environment = install.child_environment()
    assert environment["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert environment["LD_LIBRARY_PATH"] == "/system/custom"
    assert "QT_PLUGIN_PATH" not in environment
    assert os.environ["QT_PLUGIN_PATH"] == "/tmp/old-extraction/plugins"


def test_helper_readiness_precedes_client_shutdown(plan, monkeypatch):
    path, target = plan
    arguments = []

    def launch(command):
        arguments.extend(command)
        assert target.read_bytes() == OLD
        (path.parent / "ready").touch()
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(install, "_launch", launch)
    assert (
        install.start_helper(path.parent, target, install.digest(path.parent / "download"), "0.1.1")
        == path
    )
    assert arguments[1:] == ["--apply-update", path]
    assert Path(arguments[0]).read_bytes() == OLD
    assert target.read_bytes() == OLD


def test_windows_bootloader_sharing_delay_is_retried_without_killing_processes(
    tmp_path, monkeypatch
):
    source, target = tmp_path / "candidate", tmp_path / "target"
    source.write_bytes(NEW)
    target.write_bytes(OLD)
    original = os.replace
    attempts = []

    def replace(before, after):
        attempts.append(1)
        if len(attempts) <= 2:
            raise PermissionError("image still mapped")
        original(before, after)

    monkeypatch.setattr(install.os, "replace", replace)
    monkeypatch.setattr(install.time, "sleep", lambda _seconds: None)
    install._replace_wait(source, target)
    assert len(attempts) == 3 and target.read_bytes() == NEW
