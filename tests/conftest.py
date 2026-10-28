"""Desktop-only fixtures. No web server or web dependencies are loaded."""

import pytest

pytest_plugins = ["tests.qt_support"]


@pytest.fixture(autouse=True)
def isolated_download_reports(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "app-data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
