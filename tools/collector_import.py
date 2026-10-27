"""Read public osu!collector collections using the website's own JSON endpoints."""

import json
import re
import urllib.parse

from tools.beatmap_downloads import HttpClient, positive_id, valid_hash

MAX_RESPONSE = 32 * 1024 * 1024


def collection_id(value):
    value = value.strip()
    if value.isascii() and value.isdigit() and 0 < int(value) < 2**31:
        return int(value)
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ("osucollector.com", "www.osucollector.com")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Paste an HTTPS osu!collector collection URL or its numeric ID.")
    match = re.fullmatch(r"/collections/([1-9][0-9]*)(?:/[^/]*)?/?", parsed.path)
    if not match or int(match[1]) >= 2**31:
        raise ValueError(
            "Use a collection page such as https://osucollector.com/collections/44/speed-practice."
        )
    return int(match[1])


def _json(client, url):
    with client.open(url) as response:
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ValueError("The osu!collector response exceeds 32 MiB.")
    document = json.loads(data)
    if not isinstance(document, dict):
        raise ValueError("Unexpected osu!collector response.")
    return document


def fetch_collection(value, client=None):
    identifier = collection_id(value)
    client = client or HttpClient()
    base = f"https://osucollector.com/api/collections/{identifier}"
    document = _json(client, base)
    name, groups = document.get("name"), document.get("beatmapsets")
    if (
        not isinstance(name, str)
        or not name.strip()
        or "\0" in name
        or not isinstance(groups, list)
    ):
        raise ValueError("The public collection is unavailable or its response format has changed.")
    hashes, seen = [], set()
    raw_count = 0

    def include(checksum):
        nonlocal raw_count
        if not valid_hash(checksum):
            raise ValueError(
                "The collection contains an invalid or missing MD5. Nothing was imported."
            )
        raw_count += 1
        if raw_count > 1_000_000:
            raise ValueError("The collection exceeds 1,000,000 memberships.")
        checksum = checksum.lower()
        if checksum not in seen:
            seen.add(checksum)
            hashes.append(checksum)

    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("beatmaps"), list):
            raise ValueError("The collection response has incomplete beatmap data.")
        for beatmap in group["beatmaps"]:
            include(beatmap.get("checksum") if isinstance(beatmap, dict) else None)
    unknown = document.get("unknownChecksums", [])
    if not isinstance(unknown, list):
        raise ValueError("The collection response has invalid unknown checksums.")
    for checksum in unknown:
        include(checksum)
    expected = document.get("beatmapCount")
    if isinstance(expected, int) and raw_count < expected:
        raise ValueError("The collection response is incomplete. Nothing was imported.")
    metadata, warnings = {}, []
    try:
        # This is the same complete-metadata request used by the site's collection exporter.
        details = _json(client, base + "/beatmapsv3?perPage=50000")
        sets = {
            item["id"]: item
            for item in details.get("beatmapsets", [])
            if isinstance(item, dict) and "id" in item
        }
        for beatmap in details.get("beatmaps", []):
            if not isinstance(beatmap, dict):
                continue
            checksum = str(beatmap.get("checksum", "")).lower()
            if checksum not in seen:
                continue
            group = sets.get(beatmap.get("beatmapset_id"), {})

            def text(source, key):
                value = source.get(key)
                return value[:2048] if isinstance(value, str) else ""

            metadata[checksum] = {
                "Title": text(group, "title"),
                "Artist": text(group, "artist"),
                "Difficulty": text(beatmap, "version"),
                "Mode": text(beatmap, "mode"),
                "BeatmapId": positive_id(beatmap.get("id")),
                "Available": False,
            }
    except (OSError, ValueError, TypeError, KeyError):
        warnings.append(
            "Map labels could not be fetched; the collection's exact MD5s were retained."
        )
    return {
        "Collections": [{"Name": name, "Hashes": hashes}],
        "Beatmaps": metadata,
        "SourceUrl": f"https://osucollector.com/collections/{identifier}",
        "Warnings": warnings,
    }
