"""Read the same acknowledgement documents from source and PyInstaller bundles."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ("Credits", "CREDITS.md"),
    ("Project licence", "LICENSE"),
    ("Third-party notices", "THIRD_PARTY_NOTICES.md"),
)


def read_documents():
    documents = []
    bundled = getattr(sys, "_MEIPASS", None)
    for title, filename in DOCUMENTS:
        if bundled is not None:
            path = Path(bundled) / "notices" / filename
        else:
            path = ROOT / ("desktop" if filename == "THIRD_PARTY_NOTICES.md" else "") / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise RuntimeError(
                f"Could not read {filename}. Keep the complete application folder, "
                "including its notices, when copying or installing Collections Studio."
            ) from error
        if title == "Third-party notices" and os.environ.get("COLLECTIONS_STUDIO_APPIMAGE"):
            directory = (
                Path(os.environ.get("APPDIR", "")) / "usr/share/doc/CollectionsStudio-AppImage"
            )
            notices = sorted(directory.glob("*")) if directory.is_dir() else []
            if not notices:
                raise RuntimeError("The AppImage runtime licence documents are missing.")
            text += "\n\n# AppImage runtime and dependencies\n"
            for notice in notices:
                text += (
                    "\n## "
                    + notice.name
                    + "\n\n```text\n"
                    + notice.read_text(encoding="utf-8")
                    + "\n```\n"
                )
        documents.append((title, text))
    return documents
