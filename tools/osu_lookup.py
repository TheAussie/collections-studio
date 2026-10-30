"""Optional official exact-MD5 fallback. Tokens live only in memory."""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

from tools.beatmap_downloads import DownloadError, _check_cancel, mode_name, positive_id, valid_hash
from tools.osu_credentials import CredentialError, validate


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _url):
        return None


class OfficialLookup:
    def __init__(self, credentials, *, opener=None, now=time.monotonic):
        self.credentials = credentials
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.now = now
        self.lock = threading.Lock()
        self.token = ""
        self.expires = 0
        self.next_request = 0
        self.cache = OrderedDict()
        self.disabled = False

    def _request(self, path, stop, data=None):
        delay = self.next_request - self.now()
        if delay > 0 and stop.wait(delay):
            _check_cancel(stop)
        _check_cancel(stop)
        self.next_request = self.now() + 1.05
        headers = {"Accept": "application/json", "User-Agent": "CollectionsStudio/official-lookup"}
        if data is None:
            headers["Authorization"] = "Bearer " + self.token
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request("https://osu.ppy.sh" + path, headers=headers, data=data)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise DownloadError("Official API response exceeded its size limit.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            _check_cancel(stop)
            return result
        except urllib.error.HTTPError as error:
            if error.code == 429:
                try:
                    wait = min(600, max(60, int(error.headers.get("Retry-After", "60"))))
                except (ValueError, TypeError):
                    wait = 60
                self.next_request = self.now() + wait
                raise DownloadError(
                    "Official API rate limit reached; waiting before further requests."
                ) from None
            if error.code in (401, 403):
                self.disabled = True
                raise DownloadError(
                    "Official API credentials were rejected. Check your client ID and secret."
                ) from None
            if error.code == 404:
                raise DownloadError("Official API has no map with this exact MD5.") from None
            raise DownloadError("Official API is temporarily unavailable.") from None
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            raise DownloadError("Official API request failed or returned invalid data.") from None

    def resolve(self, checksum, stop):
        if not valid_hash(checksum):
            raise DownloadError("Official lookup requires an exact valid MD5.")
        checksum = checksum.lower()
        with self.lock:
            _check_cancel(stop)
            if checksum in self.cache:
                return self.cache[checksum]
            if self.disabled:
                raise DownloadError(
                    "Official API is disabled for this queue after an authentication failure."
                )
            if self.next_request - self.now() > 2:
                raise DownloadError("Official API is cooling down after a rate limit.")
            if self.expires <= self.now():
                try:
                    pair = self.credentials()
                    if pair is None:
                        raise CredentialError("Configure osu! API credentials first.")
                    client_id, secret = validate(*pair)
                except CredentialError:
                    self.disabled = True
                    raise DownloadError(
                        "Official API credentials are unavailable. Configure or unlock them first."
                    ) from None
                token = self._request(
                    "/oauth/token",
                    stop,
                    urllib.parse.urlencode(
                        {
                            "client_id": client_id,
                            "client_secret": secret,
                            "grant_type": "client_credentials",
                            "scope": "public",
                        }
                    ).encode(),
                )
                lifetime = token.get("expires_in")
                if (
                    not isinstance(token.get("access_token"), str)
                    or not token["access_token"]
                    or len(token["access_token"]) > 4096
                    or type(lifetime) is not int
                    or lifetime <= 0
                ):
                    raise DownloadError("Official API returned an invalid access token.")
                self.token = token["access_token"]
                self.expires = self.now() + max(0, lifetime - 30)
            item = self._request(
                "/api/v2/beatmaps/lookup?" + urllib.parse.urlencode({"checksum": checksum}), stop
            )
            if str(item.get("checksum", "")).lower() != checksum:
                raise DownloadError(
                    "Official API returned a different MD5; no replacement was accepted."
                )
            set_id = positive_id(item.get("beatmapset_id"))
            beatmap_id = positive_id(item.get("id"))
            if not set_id or not beatmap_id:
                raise DownloadError("Official API returned invalid beatmap identifiers.")
            group = item.get("beatmapset")
            if not isinstance(group, dict):
                group = self._request(f"/api/v2/beatmapsets/{set_id}", stop)
            if positive_id(group.get("id")) != set_id:
                raise DownloadError("Official API returned inconsistent beatmapset identifiers.")
            result = (
                set_id,
                {
                    "Title": str(group.get("title", ""))[:2048],
                    "Artist": str(group.get("artist", ""))[:2048],
                    "Difficulty": str(item.get("version", ""))[:2048],
                    "BeatmapId": beatmap_id,
                    "Mode": mode_name(item.get("mode_int", item.get("mode"))),
                },
            )
            self.cache[checksum] = result
            while len(self.cache) > 4096:
                self.cache.popitem(last=False)
            return result
