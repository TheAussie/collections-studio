"""Optional user-owned API credentials in native vaults; never plaintext settings."""

import ctypes
import json
import os
import shutil
import subprocess
import sys

SERVICE = "CollectionsStudio/osu-api"


class CredentialError(ValueError):
    pass


def validate(client_id, secret):
    client_id = str(client_id).strip()
    if (
        len(client_id) > 20
        or not client_id.isascii()
        or not client_id.isdecimal()
        or int(client_id) <= 0
    ):
        raise CredentialError("Enter a positive numeric osu! client ID.")
    if (
        not isinstance(secret, str)
        or not 1 <= len(secret) <= 512
        or any(ord(c) < 32 for c in secret)
    ):
        raise CredentialError("Enter the osu! OAuth client secret.")
    return client_id, secret


class CredentialStore:
    def _windows(self, action, value=None):
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        api = ctypes.WinDLL("Advapi32", use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(Credential)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        if action == "save":
            raw = value.encode("utf-8")
            blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            record = Credential(
                Type=1,
                TargetName=SERVICE,
                CredentialBlobSize=len(raw),
                CredentialBlob=blob,
                Persist=2,
                UserName="osu-api",
            )
            ok = api.CredWriteW(ctypes.byref(record), 0)
        elif action == "delete":
            ok = api.CredDeleteW(SERVICE, 1, 0)
        else:
            record = ctypes.POINTER(Credential)()
            ok = api.CredReadW(SERVICE, 1, 0, ctypes.byref(record))
            if ok:
                try:
                    return ctypes.string_at(
                        record.contents.CredentialBlob, record.contents.CredentialBlobSize
                    ).decode("utf-8")
                finally:
                    api.CredFree(record)
        if not ok and (action == "save" or ctypes.get_last_error() != 1168):
            raise CredentialError("Windows Credential Manager could not complete the operation.")
        return None

    def _operation(self, action, value=None):
        if sys.platform == "win32":
            return self._windows(action, value)
        tool = shutil.which("secret-tool") if sys.platform == "linux" else None
        if not tool:
            raise CredentialError(
                "Secure storage needs Linux Secret Service and secret-tool (libsecret). "
                "Use this session only instead."
            )
        command = [tool, {"save": "store", "load": "lookup", "delete": "clear"}[action]]
        if action == "save":
            command += ["--label=Collections Studio osu! API"]
        command += ["application", "collections-studio", "purpose", "osu-api"]
        try:
            environment = dict(os.environ)
            original = environment.get("LD_LIBRARY_PATH_ORIG")
            if original is None:
                environment.pop("LD_LIBRARY_PATH", None)
            else:
                environment["LD_LIBRARY_PATH"] = original
            result = subprocess.run(
                command,
                input=value,
                text=True,
                capture_output=True,
                env=environment,
                timeout=10 if action == "load" else 120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise CredentialError("The system credential store is unavailable or locked.") from None
        if result.returncode and (action == "save" or result.stderr.strip()):
            raise CredentialError("Unlock your system credential store or use this session only.")
        return result.stdout.strip() or None

    def save(self, client_id, secret):
        pair = validate(client_id, secret)
        self._operation("save", json.dumps(pair))
        return pair

    def load(self):
        try:
            raw = self._operation("load")
            if raw is None:
                return None
            pair = json.loads(raw)
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError
            return validate(*pair)
        except (ValueError, TypeError):
            raise CredentialError(
                "The saved osu! credentials are invalid; replace or forget them."
            ) from None

    def delete(self):
        self._operation("delete")
