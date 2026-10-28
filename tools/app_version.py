"""Version from source metadata or the metadata embedded in a portable build."""

import json
import re
import sys
import tomllib
from pathlib import Path


def current_version():
    if getattr(sys, "frozen", False):
        return json.loads((Path(sys._MEIPASS) / "app-version.json").read_text(encoding="utf-8"))[
            "version"
        ]
    return tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]


def version_key(value):
    match = re.fullmatch(
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(-[0-9A-Za-z.-]+|(?:a|b|rc)\d+|\.dev\d+))?(?:\+[0-9A-Za-z.-]+)?",
        value,
    )
    if not match:
        raise ValueError("Unsupported application version.")
    return (*map(int, match.group(1, 2, 3)), not bool(match.group(4)))
