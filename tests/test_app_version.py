import argparse
import json

import pytest

from desktop import build_desktop
from tools import app_version


def test_frozen_version_uses_embedded_metadata(monkeypatch, tmp_path):
    (tmp_path / "app-version.json").write_text(
        json.dumps({"version": "0.2.3", "format": "onefile"})
    )
    monkeypatch.setattr(app_version.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_version.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert app_version.current_version() == "0.2.3"


@pytest.mark.parametrize(
    "tag, version, valid",
    [
        ("", "0.1.1", True),
        ("v0.1.1", "0.1.1", True),
        ("v0.1.0", "0.1.1", False),
        ("v0.2.0-beta.1", "0.2.0b1", True),
        ("v0.2.0b1", "0.2.0b1", False),
    ],
)
def test_release_tag_matches_project_version_before_build(
    monkeypatch, tmp_path, tag, version, valid
):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    monkeypatch.setattr(build_desktop, "ROOT", tmp_path)
    monkeypatch.setenv("COLLECTIONS_STUDIO_RELEASE_TAG", tag)
    if valid:
        assert build_desktop.application_version(argparse.ArgumentParser()) == (
            tag[1:] if tag else version
        )
    else:
        with pytest.raises(SystemExit):
            build_desktop.application_version(argparse.ArgumentParser())
