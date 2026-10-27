"""Import versioned Maps snapshot links or public osu!collector collections."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from tools.beatmap_downloads import USER_AGENT, positive_id, valid_hash

MAX_BYTES = 32 * 1024 * 1024


def maps_url(value):
    value = value.strip()
    try:
        parsed = urllib.parse.urlsplit(value)
        local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            len(value) > 2048
            or any(ord(character) <= 32 for character in value)
            or not parsed.hostname
            or (parsed.scheme != "https" and not local)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
            or not re.fullmatch(r"/api/v1/collections/[A-Za-z0-9_-]{43}", parsed.path)
        ):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise ValueError(
            "Paste the Maps import link created on its export review page. "
            "Use HTTPS, or loopback HTTP for local development."
        ) from None
    return value


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        # Never forward a secret link to another endpoint, even on the same host.
        return None


class MapsClient:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects())

    def open(self, url):
        return self.opener.open(
            urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            ),
            timeout=20,
        )


def parse_snapshot(document):
    if (
        not isinstance(document, dict)
        or document.get("Format") != "maps-collection"
        or type(document.get("Version")) is not int
        or document["Version"] != 1
    ):
        raise ValueError("This is not a supported Maps collection snapshot (version 1).")
    raw_groups = document.get("Collections")
    if not isinstance(raw_groups, list) or not 1 <= len(raw_groups) <= 100:
        raise ValueError("The snapshot must contain between 1 and 100 collections.")
    groups, seen_hashes, raw_count = [], set(), 0
    for group in raw_groups:
        if not isinstance(group, dict):
            raise ValueError("The snapshot has incomplete collection data.")
        name, hashes = group.get("Name"), group.get("Hashes")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or "\0" in name
            or not isinstance(hashes, list)
            or len(hashes) > 10_000
            or any(not valid_hash(checksum) for checksum in hashes)
        ):
            raise ValueError("The snapshot contains an invalid collection name or MD5 membership.")
        raw_count += len(hashes)
        normalized = list(dict.fromkeys(checksum.lower() for checksum in hashes))
        seen_hashes.update(normalized)
        groups.append({"Name": name, "Hashes": normalized})
    if (
        type(document.get("CollectionCount")) is not int
        or document["CollectionCount"] != len(groups)
        or type(document.get("MembershipCount")) is not int
        or document["MembershipCount"] != raw_count
    ):
        raise ValueError("The snapshot is incomplete: its collection or membership count differs.")
    raw_metadata = document.get("Beatmaps", {})
    if not isinstance(raw_metadata, dict):
        raise ValueError("The snapshot has invalid beatmap labels.")
    metadata = {}
    for checksum, details in raw_metadata.items():
        if not valid_hash(checksum) or checksum.lower() not in seen_hashes:
            continue
        if not isinstance(details, dict):
            continue
        fields = {}
        for field in ("Title", "Artist", "Difficulty", "Mode"):
            value = details.get(field, "")
            fields[field] = value[:2048] if isinstance(value, str) else ""
        metadata[checksum.lower()] = {
            **fields,
            "BeatmapId": positive_id(details.get("BeatmapId")),
            "Available": False,
        }
    return {"Collections": groups, "Beatmaps": metadata, "Warnings": []}


def fetch_maps(value, client=None):
    url = maps_url(value)
    client = client or MapsClient()
    try:
        with client.open(url) as response:
            if (
                response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                != "application/json"
            ):
                raise ValueError(
                    "The link did not return collection JSON. Create a Maps import link."
                )
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("The Maps response exceeds 32 MiB.")
        document = json.loads(data)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code in (401, 403, 404):
            raise ValueError("The Maps import link is unavailable or has been revoked.") from None
        if 300 <= error.code < 400:
            raise ValueError(
                "The Maps link redirected. Paste its original, direct import link."
            ) from None
        raise ValueError(
            "The Maps website could not complete the request. Try again later."
        ) from None
    except (OSError, UnicodeError, RecursionError):
        raise ValueError(
            "The Maps website could not be reached or returned unreadable JSON."
        ) from None
    except json.JSONDecodeError:
        raise ValueError(
            "The Maps website returned unreadable JSON. Nothing was imported."
        ) from None
    return {**parse_snapshot(document), "SourceUrl": url, "SourceName": "Maps"}


def fetch_link(value, client=None):
    if "/api/v1/collections/" in value:
        return fetch_maps(value, client)
    from tools.collector_import import fetch_collection

    document = fetch_collection(value) if client is None else fetch_collection(value, client)
    return {**document, "SourceName": "osu!collector"}
