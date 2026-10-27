import io
import json
import urllib.error
import urllib.request
import urllib.response
from email.message import Message

import pytest

from tools import collection_links as links

URL = "https://maps.test/api/v1/collections/" + "a" * 43
A, B = "a" * 32, "b" * 32


def snapshot():
    return {
        "Format": "maps-collection",
        "Version": 1,
        "CollectionCount": 2,
        "MembershipCount": 1,
        "Collections": [{"Name": "練習 🎵", "Hashes": [A]}, {"Name": "Empty", "Hashes": []}],
        "Beatmaps": {
            A: {"Title": "Song", "Artist": "Artist", "Difficulty": "Hard", "Available": True}
        },
    }


class Client:
    def __init__(self, data=None, content_type="application/json; charset=utf-8", error=None):
        self.data = json.dumps(snapshot()).encode() if data is None else data
        self.content_type = content_type
        self.error = error
        self.calls = []

    def open(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        response = io.BytesIO(self.data)
        response.headers = {"Content-Type": self.content_type}
        return response


@pytest.mark.parametrize(
    "url",
    [
        "http://maps.test/api/v1/collections/" + "a" * 43,
        "https://user:pass@maps.test/api/v1/collections/" + "a" * 43,
        "https://maps.test:invalid/api/v1/collections/" + "a" * 43,
        "https://maps.test/collections/1",
        URL + "?redirect=elsewhere",
        URL + "?",
        URL + "#fragment",
        URL + "#",
        URL + "/collection.db",
        URL[:-1],
        "https://maps.test\n.evil.test/api/v1/collections/" + "a" * 43,
        "file:///api/v1/collections/" + "a" * 43,
    ],
)
def test_invalid_maps_links_never_make_a_request(url):
    client = Client()
    with pytest.raises(ValueError, match="Maps import link"):
        links.fetch_maps(url, client)
    assert not client.calls


@pytest.mark.parametrize(
    "origin",
    ["https://maps.example", "http://localhost:8765", "http://127.0.0.1:8765", "http://[::1]:8765"],
)
def test_direct_links_allow_custom_https_origin_and_loopback_development(origin):
    url = origin + "/api/v1/collections/" + "a" * 43
    document = links.fetch_link(url, Client())
    assert document["Collections"] == snapshot()["Collections"]
    assert document["Beatmaps"][A]["Available"] is False
    assert document["SourceName"] == "Maps"


@pytest.mark.parametrize(
    "field,value",
    [
        ("Format", "unknown"),
        ("Version", True),
        ("Version", 2),
        ("CollectionCount", 3),
        ("CollectionCount", True),
        ("MembershipCount", 2),
        ("MembershipCount", True),
        ("Collections", []),
        ("Beatmaps", []),
    ],
)
def test_unsupported_or_incomplete_snapshot_fails_entire_import(field, value):
    document = snapshot()
    document[field] = value
    with pytest.raises(ValueError):
        links.fetch_maps(URL, Client(json.dumps(document).encode()))


@pytest.mark.parametrize(
    "group",
    [
        None,
        {"Name": "Main", "Hashes": ["invalid"]},
        {"Name": "Main"},
        {"Name": "", "Hashes": []},
        {"Name": "x\0y", "Hashes": []},
        {"Name": "x" * 81, "Hashes": []},
    ],
)
def test_invalid_membership_or_name_never_imports_a_partial_collection(group):
    document = snapshot()
    document["Collections"][1] = group
    with pytest.raises(ValueError):
        links.parse_snapshot(document)


def test_md5_dedup_retains_unknown_hashes_and_shared_membership_in_other_collections():
    document = snapshot()
    document["Collections"] = [
        {"Name": "Main", "Hashes": [A, A.upper(), B]},
        {"Name": "Other", "Hashes": [B]},
    ]
    document["MembershipCount"] = 4
    document["Beatmaps"]["c" * 32] = {"Title": "Unrelated"}
    result = links.parse_snapshot(document)
    assert result["Collections"] == [
        {"Name": "Main", "Hashes": [A, B]},
        {"Name": "Other", "Hashes": [B]},
    ]
    assert list(result["Beatmaps"]) == [A]
    assert result["Beatmaps"][A]["Available"] is False


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 404, 429, 500, 503])
def test_http_errors_are_actionable_and_never_echo_secret_url(status):
    client = Client(error=urllib.error.HTTPError(URL, status, "Failed " + URL, {}, None))
    with pytest.raises(ValueError) as failure:
        links.fetch_maps(URL, client)
    assert URL not in str(failure.value) and "a" * 43 not in str(failure.value)
    assert len(client.calls) == 1


def test_real_urllib_redirect_handler_does_not_follow_or_disclose_link():
    calls = []

    class RedirectResponse(urllib.request.HTTPSHandler):
        def https_open(self, request):
            calls.append(request.full_url)
            assert len(calls) == 1
            assert request.get_header("Accept") == "application/json"
            assert request.get_header("Authorization") is None
            assert request.get_header("Cookie") is None
            headers = Message()
            headers["Location"] = "https://other.test/stolen"
            response = urllib.response.addinfourl(io.BytesIO(), headers, request.full_url, 302)
            response.msg = "Found"
            return response

    client = links.MapsClient()
    client.opener = urllib.request.build_opener(RedirectResponse(), links.NoRedirects())
    with pytest.raises(ValueError, match="redirected"):
        links.fetch_maps(URL, client)
    assert calls == [URL]


def test_html_malformed_json_and_size_limit_are_rejected(monkeypatch):
    with pytest.raises(ValueError, match="collection JSON"):
        links.fetch_maps(URL, Client(b"<html>Sign in</html>", "text/html"))
    with pytest.raises(ValueError, match="unreadable JSON"):
        links.fetch_maps(URL, Client(b"{bad"))
    monkeypatch.setattr(links, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="32 MiB"):
        links.fetch_maps(URL, Client())
