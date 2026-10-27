import argparse
import subprocess

import pytest

from desktop import build_desktop


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (FileNotFoundError(), "dotnet.exe was not found on PATH"),
        (subprocess.CalledProcessError(1, ["dotnet", "--version"]), "is unavailable"),
        ("10.0.999", "found 10.0.999"),
    ],
)
def test_sdk_prerequisite_failure_is_actionable_without_traceback(
    monkeypatch, capsys, outcome, message
):
    def check(*args, **kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(build_desktop.subprocess, "check_output", check)
    with pytest.raises(SystemExit) as error:
        build_desktop.check_sdk(argparse.ArgumentParser())
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert message in stderr
    assert build_desktop.SDK in stderr
    assert "Traceback" not in stderr


def test_sdk_prerequisite_uses_the_pinned_global_json(monkeypatch):
    def check(arguments, **options):
        assert arguments == ["dotnet", "--version"]
        assert options["cwd"] == build_desktop.ROOT / "desktop"
        assert options["stderr"] == subprocess.STDOUT
        return build_desktop.SDK + "\n"

    monkeypatch.setattr(build_desktop.subprocess, "check_output", check)
    build_desktop.check_sdk(argparse.ArgumentParser())


@pytest.mark.parametrize("onefile", [False, True])
def test_spec_marks_native_helper_executable_and_selects_requested_bundle_layout(
    tmp_path, monkeypatch, onefile
):
    import runpy
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    stage = tmp_path / "stage"
    helper = (
        stage
        / "backend"
        / ("realm-collection-import.exe" if sys.platform == "win32" else "realm-collection-import")
    )
    monkeypatch.setenv("COLLECTIONS_STUDIO_STAGE", str(stage))
    monkeypatch.setenv("COLLECTIONS_STUDIO_ONEFILE", "1" if onefile else "0")
    calls = []

    def analysis(*args, **kwargs):
        assert kwargs["binaries"] == [(str(helper), "backend")]
        return SimpleNamespace(
            pure=[],
            scripts=[],
            binaries=[("backend/helper", str(helper), "BINARY")],
            datas=[
                ("backend/helper", str(helper), "DATA"),
                ("notices/LICENSE", str(stage / "notices/LICENSE"), "DATA"),
            ],
        )

    def executable(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    collections = []
    spec = Path(build_desktop.__file__).with_name("collections-studio.spec")
    scope = runpy.run_path(
        str(spec),
        init_globals={
            "SPECPATH": str(spec.parent),
            "Analysis": analysis,
            "PYZ": lambda _: object(),
            "EXE": executable,
            "COLLECT": lambda *args, **kwargs: collections.append((args, kwargs)),
        },
    )
    assert len(calls) == 1
    assert bool(collections) is not onefile
    assert calls[0][1].get("exclude_binaries", False) is not onefile
    assert all(entry[2] != "DATA" or entry[1] != str(helper) for entry in scope["a"].datas)
