import sys

import pytest

from tools import credits
from tools.beatmap_downloads import MIRRORS


def test_source_credits_cover_services_and_project_licence():
    documents = dict(credits.read_documents())
    assert "MIT License" in documents["Project licence"]
    assert "TheAussie" in documents["Project licence"]
    for mirror in MIRRORS:
        assert mirror.name in documents["Credits"]
    for name in ("osu!collector", "Replay Parser", "PySide6", "Realm", "OpenAI Codex"):
        assert name in documents["Credits"]
    assert "LGPL" in documents["Third-party notices"]


def test_bundled_viewer_uses_packaged_documents_without_source_tree(tmp_path, monkeypatch):
    notices = tmp_path / "notices"
    notices.mkdir()
    for title, filename in credits.DOCUMENTS:
        (notices / filename).write_text("Bundled " + title, encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(credits, "ROOT", tmp_path / "missing source tree")
    assert credits.read_documents() == [
        (title, "Bundled " + title) for title, _ in credits.DOCUMENTS
    ]


@pytest.mark.parametrize("missing", [filename for _, filename in credits.DOCUMENTS])
def test_incomplete_bundle_reports_missing_document(tmp_path, monkeypatch, missing):
    notices = tmp_path / "notices"
    notices.mkdir()
    for _, filename in credits.DOCUMENTS:
        if filename != missing:
            (notices / filename).write_text("Document", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(RuntimeError, match=missing):
        credits.read_documents()
