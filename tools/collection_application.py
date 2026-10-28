"""Presentation-free orchestration; parsers and new-copy verification stay authoritative."""

import json
import tempfile
from pathlib import Path

from tools.stable_collections import read_stable, save_stable


def fetch_cancellable_link(value, stop):
    from tools.beatmap_downloads import HttpClient, _check_cancel
    from tools.collection_links import MapsClient, fetch_link

    transport = MapsClient() if "/api/v1/collections/" in value else HttpClient()

    class Client:
        def open(self, url):
            _check_cancel(stop)
            return transport.open(url)

    document = fetch_link(value, client=Client())
    _check_cancel(stop)
    return document


def load_document(
    path, backend, *, library_source=None, cache_directory=None, stop=None, progress=None
):
    if str(path).lower().endswith(".realm"):
        return backend.run("inspect", realm_copy=path)
    document = read_stable(path)
    from tools.library_cache import cache_database_inventory, restore_library
    from tools.osu_database import read_osu_database

    if library_source is not None:
        try:
            inventory = restore_library(library_source, stop=stop, progress=progress)
            document.update(
                {key: inventory[key] for key in ("Beatmaps", "LibrarySource", "LibraryNotice")}
            )
            return document
        except (ValueError, OSError, TypeError, KeyError) as error:
            document["LibraryError"] = f"Saved song library could not be restored: {error}"
    for name in ("osu!.db", "osu.db"):
        database = Path(path).with_name(name)
        if database.is_file():
            try:
                document["Beatmaps"] = read_osu_database(database)["Beatmaps"]
                if cache_directory is not None:
                    document["LibrarySource"] = cache_database_inventory(
                        database, document, cache_directory
                    )
                    document["LibraryNotice"] = "Saved song library for future opens."
            except (ValueError, OSError) as error:
                document["LibraryError"] = str(error)
            break
    return document


def save_workspace(workspace, output, backend):
    if workspace.format == "stable":
        return save_stable(workspace, output)
    with tempfile.TemporaryDirectory(prefix="collections-plan-") as temporary:
        path = Path(temporary) / "plan.json"
        path.write_text(json.dumps(workspace.plan()), encoding="utf-8")
        path.chmod(0o600)
        return backend.run(
            "edit", plan=path, realm_copy=workspace.source_path, output_directory=output
        )
