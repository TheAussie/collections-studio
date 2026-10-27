"""Verify normal Qt Save on a disposable Realm, including actual SDK lock refusal."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from tools.collection_backend import PROJECT, Backend  # noqa: E402
from tools.collection_save import save_open_workspace  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.qt_collection_studio import StudioWindow, configure_appearance  # noqa: E402
from tools.qt_dialog_support import finish_shutdown  # noqa: E402
from tools.stable_collections import digest  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--realm-fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir()
    fixture_hash = digest(args.realm_fixture)
    source = output / "client.realm"
    shutil.copyfile(args.realm_fixture, source)
    source.chmod(0o600)
    backend = Backend()
    workspace = Workspace(backend.run("inspect", realm_copy=source), str(source))
    group = next(group for group in workspace.collections if group["Name"] == "Smoke - Main")
    workspace.rename(group["Id"], "Save check 練習 🎵")
    probe = output / "lock-probe"
    probe.mkdir()
    project = probe / "RealmHold.csproj"
    project.write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        "<TargetFramework>net8.0</TargetFramework><DisableFody>true</DisableFody>"
        '</PropertyGroup><ItemGroup><ProjectReference Include="'
        + escape(str(PROJECT))
        + '" /></ItemGroup></Project>',
        encoding="utf-8",
    )
    (probe / "Program.cs").write_text(
        "using System; using Realms;"
        "using var realm = Realm.GetInstance(new RealmConfiguration(args[0]) { IsDynamic = true });"
        'Console.WriteLine("REALM_OPEN"); Console.Out.Flush(); Console.ReadLine();',
        encoding="utf-8",
    )
    built = subprocess.run(
        ["dotnet", "build", str(project), "-c", "Release", "--nologo"],
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    (output / "lock-probe-build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
    process = subprocess.Popen(
        ["dotnet", str(probe / "bin/Release/net8.0/RealmHold.dll"), str(source)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "REALM_OPEN", process.stderr.read()
        try:
            save_open_workspace(workspace, backend)
        except PermissionError:
            pass
        else:
            raise AssertionError("Save accepted a Realm currently open in the SDK")
        assert digest(source) == fixture_hash and not list(output.glob("*.backup-*.realm"))
    finally:
        process.communicate("\n", timeout=30)
    print("Actual Realm SDK open-file refusal passed", flush=True)

    application = QApplication([])
    configure_appearance(application)
    window = StudioWindow(
        backend=backend,
        settings=QSettings(str(output / "settings.ini"), QSettings.Format.IniFormat),
    )
    window.workspace = workspace
    window.refresh_collections()
    window.show()
    errors = []
    QMessageBox.critical = lambda *_args: errors.append(_args[-1])

    def save():
        window.save_button.click()
        deadline = time.monotonic() + 180
        while window.job and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        application.processEvents()
        assert not window.job and not errors, errors
        assert window.workspace.source_path == str(source) and not window.workspace.dirty
        assert window.workspace.source_hash == digest(source)

    save()
    first = json.loads(next(output.glob("*.save-report-*.json")).read_text())
    assert first["SaveState"] == "saved" and first["VerifiedAfterReopen"]
    assert digest(first["BackupFile"]) == fixture_hash
    reopened = backend.run("inspect", realm_copy=source)
    assert (
        next(g for g in reopened["Collections"] if g["Id"] == group["Id"])["Name"]
        == "Save check 練習 🎵"
    )
    previous = digest(source)
    window.workspace.rename(group["Id"], "Second Save check")
    window.refresh_collections()
    save()
    reports = [json.loads(path.read_text()) for path in output.glob("*.save-report-*.json")]
    second = next(report for report in reports if report["BackupFile"] != first["BackupFile"])
    assert digest(second["BackupFile"]) == previous
    assert digest(first["BackupFile"]) == fixture_hash
    reopened = backend.run("inspect", realm_copy=source)
    assert (
        next(g for g in reopened["Collections"] if g["Id"] == group["Id"])["Name"]
        == "Second Save check"
    )
    assert digest(args.realm_fixture) == fixture_hash
    screenshot = output / "save-complete.png"
    assert window.grab().save(str(screenshot))
    window.close()
    finish_shutdown(window)
    report = {
        "Result": "passed",
        "ActualRealmSdkLockRefused": True,
        "TwoQtSavesUpdatedOriginalPath": True,
        "ByteExactBackupForEachSave": True,
        "NativeAuditsAndReopenPassed": True,
        "FixtureSourceUnchanged": True,
        "OriginalFixtureSha256": fixture_hash,
        "UsesLiveGameDatabases": False,
        "Screenshot": str(screenshot),
        "SaveReports": reports,
    }
    (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Two native Qt saves, exact backups and reopening verified", flush=True)
    print("Evidence:", output, flush=True)


if __name__ == "__main__":
    main()
