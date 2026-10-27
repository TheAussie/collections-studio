import io
import json
from pathlib import Path

from tools.collection_links import fetch_link
from tools.collection_workspace import Workspace
from tools.stable_collections import decode, encode


def test_snapshot_import_and_stable_roundtrip_match_server_contract():
    fixtures = Path(__file__).parent / "fixtures"
    payload = (fixtures / "collection-link-v1.json").read_bytes()
    expected = json.loads(payload)
    url = "https://maps.test/api/v1/collections/" + "a" * 43

    class Transport:
        def open(self, requested):
            assert requested == url
            response = io.BytesIO(payload)
            response.headers = {"Content-Type": "application/json"}
            return response

    document = fetch_link(url, Transport())
    workspace = Workspace({"Format": "stable", "SourceRealmSha256": "", "Collections": []}, "")
    assert workspace.merge(document["Collections"]) == (2, 1)
    assert workspace.merge(document["Collections"]) == (0, 0)
    assert document["Beatmaps"]["a" * 32]["Available"] is False
    binary = encode(workspace.collections)
    assert binary == bytes.fromhex((fixtures / "collection-db-v1.hex").read_text())
    assert [
        {"Name": group["Name"], "Hashes": group["Hashes"]}
        for group in decode(binary)["Collections"]
    ] == expected["Collections"]
