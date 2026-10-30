"""Explicit per-user Linux installation. Never opens game files or credential stores."""

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from tools.beatmap_downloads import _check_cancel
from tools.collection_save import database_save_lock

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "collections-studio"
OWNER = "CollectionsStudio-user-install-v1"


class InstallError(ValueError):
    pass


@dataclass(frozen=True)
class Artifact:
    path: Path
    kind: str


@dataclass(frozen=True)
class Layout:
    data: Path
    desktop_dir: Path | None = None

    @property
    def root(self):
        return self.data / APP_ID / "installation"

    @property
    def binary(self):
        return self.root / "CollectionsStudio"

    @property
    def manifest(self):
        return self.root / "installation.json"

    @property
    def icon(self):
        return self.data / "icons/hicolor/scalable/apps/collections-studio.svg"

    @property
    def launcher(self):
        return self.data / "applications/collections-studio.desktop"

    @property
    def desktop(self):
        return self.desktop_dir / "collections-studio.desktop" if self.desktop_dir else None

    def roles(self):
        return {
            "binary": self.binary,
            "icon": self.icon,
            "launcher": self.launcher,
            **({"desktop": self.desktop} if self.desktop else {}),
        }


def user_layout(desktop_dir=None):
    configured = os.environ.get("XDG_DATA_HOME", "")
    data = (
        Path(configured)
        if configured and Path(configured).is_absolute()
        else Path.home() / ".local/share"
    )
    desktop = Path(desktop_dir).resolve() if desktop_dir else None
    if desktop is not None and (not desktop.is_dir() or desktop == Path.home().resolve()):
        desktop = None
    return Layout(data.resolve(), desktop)


def icon_path():
    bundle = getattr(sys, "_MEIPASS", None)
    return (
        Path(bundle) / "assets/collections-studio.svg"
        if bundle
        else ROOT / "desktop/assets/collections-studio.svg"
    )


def running_artifact():
    if sys.platform != "linux" or not getattr(sys, "frozen", False):
        raise InstallError(
            "Installation is available from the packaged Linux binary or AppImage. "
            "Source checkouts continue to run from source."
        )
    try:
        details = json.loads((Path(sys._MEIPASS) / "app-version.json").read_text())
        if details.get("format") != "onefile":
            raise InstallError("Use the standalone binary or AppImage to install.")
        image = bool(os.environ.get("COLLECTIONS_STUDIO_APPIMAGE"))
        if image and not os.environ.get("APPIMAGE"):
            raise InstallError(
                "Start the original AppImage file to install it, rather than its extracted payload."
            )
        path = Path(os.environ["APPIMAGE"] if image else sys.executable).resolve(strict=True)
        return Artifact(path, "appimage" if image else "binary")
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise InstallError(
            "The running portable file is unavailable. Start the original download again."
        ) from error


def _safe(path, base):
    if not path.is_relative_to(base):
        raise InstallError("The installation path is outside its user directory.")
    for part in (base, *reversed(path.relative_to(base).parents)):
        candidate = part if part == base else base / part
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_dir()):
            raise InstallError(
                "An installation directory is a symbolic link or is not a directory."
            )
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise InstallError(f"Refusing to replace a symbolic link or special file: {path}")


def _check_layout(layout):
    if sys.platform != "linux":
        raise InstallError("Per-user installation currently supports Linux.")
    if not layout.data.is_absolute() or layout.data != layout.data.resolve():
        raise InstallError("Choose an absolute, resolved user data directory.")
    for path in (layout.binary, layout.manifest, layout.icon, layout.launcher):
        _safe(path, layout.data)


def _identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise InstallError(f"Not a regular installation file: {path}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def installation(layout):
    _check_layout(layout)
    if not layout.manifest.exists():
        return None
    if layout.manifest.stat().st_size > 64 * 1024:
        raise InstallError("The installation record is too large.")
    try:
        record = json.loads(layout.manifest.read_text())
        if record["owner"] != OWNER or record["kind"] not in ("binary", "appimage"):
            raise ValueError
        if not isinstance(record["version"], str) or len(record["version"]) > 100:
            raise ValueError
        files = record["files"]
        if (
            not isinstance(files, dict)
            or not {"binary", "icon", "launcher"} <= files.keys()
            or files.keys() - {"binary", "icon", "launcher", "desktop"}
        ):
            raise ValueError
        for role, row in files.items():
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("sha256"), str)
                or len(row["sha256"]) != 64
            ):
                raise ValueError
            if any(char not in "0123456789abcdef" for char in row["sha256"]):
                raise ValueError
            stored = row.get("path")
            if not isinstance(stored, str) or len(stored) > 4096 or not Path(stored).is_absolute():
                raise ValueError
            if role == "desktop" and Path(stored).name != "collections-studio.desktop":
                raise ValueError
            # Desktop locations can legitimately change; never follow an old or
            # forged path from a manifest to another directory during uninstall.
            if role != "desktop" and row.get("path") != str(layout.roles()[role]):
                raise ValueError
        return record
    except (KeyError, TypeError, ValueError) as error:
        raise InstallError(
            "The installation record is invalid. No files have been changed."
        ) from error


def _entry_argument(value):
    text = str(value)
    if any(char in text for char in ("\n", "\r", "\0", "=")):
        raise InstallError(
            "The installation location contains a character unsupported by Linux launchers."
        )
    quoted = "".join("\\" + char if char in '\\"`$' else char for char in text)
    return '"' + quoted.replace("\\", "\\\\").replace("%", "%%") + '"'


def desktop_entry(layout):
    executable = _entry_argument(layout.binary)
    icon = str(layout.icon).replace("\\", "\\\\")
    return (
        "[Desktop Entry]\nType=Application\nName=Collections Studio\n"
        f"Exec={executable}\nIcon={icon}\nTerminal=false\nCategories=Game;\n"
        "StartupWMClass=CollectionsStudioQt\nActions=Uninstall;\n\n"
        "[Desktop Action Uninstall]\nName=Uninstall Collections Studio…\n"
        f"Exec={executable} --manage-installation\nIcon=edit-delete\n"
    ).encode()


def _copy(source, destination, stop):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(source, flags), "rb") as incoming, destination.open("xb") as outgoing:
        if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
            raise InstallError("Copy requires a regular portable application file.")
        before = _identity(source)
        while True:
            _check_cancel(stop)
            block = incoming.read(1024 * 1024)
            if not block:
                break
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
        if _identity(source) != before:
            raise InstallError("The portable file changed during copying. Try again.")
    shutil.copymode(source, destination)


def _transaction(layout, writes, removals, stop, managed, expected=None):
    """Back up originals, stage on each target filesystem, rollback ordinary errors."""
    store = layout.data / APP_ID / "installation-backups"
    _safe(store / "placeholder", layout.data)
    store.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="transaction-", dir=store))
    originals, stages, changed = {}, {}, []
    try:
        for index, path in enumerate([*writes, *removals]):
            _check_layout(layout)
            _safe(path, layout.desktop_dir if path == layout.desktop else layout.data)
            original = _identity(path)
            saved = backup / str(index)
            originals[path] = (original, saved)
            if original is not None:
                _copy(path, saved, stop)
                if _identity(path) != original:
                    raise InstallError("An installation file changed. Try again.")
        journal = {
            str(path): str(saved) if original else None
            for path, (original, saved) in originals.items()
        }
        (backup / "restore.json").write_text(json.dumps(journal, indent=2))
        for path, content in writes.items():
            _check_cancel(stop)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".studio-install-", dir=path.parent)
            os.close(fd)
            staged = Path(name)
            stages[path] = staged
            if isinstance(content, Path):
                staged.unlink()  # Only this exclusive empty staging file.
                _copy(content, staged, stop)
            else:
                with staged.open("wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            if expected and path in expected and _hash(staged) != expected[path]:
                raise InstallError(
                    "The portable file or icon changed while preparing installation."
                )
            staged.chmod(0o755 if path == layout.binary or path == layout.desktop else 0o644)
            if path == layout.manifest:
                staged.chmod(0o600)
        _check_cancel(stop)
        for path in [*writes, *removals]:
            _check_layout(layout)
            _safe(path, layout.desktop_dir if path == layout.desktop else layout.data)
            if _identity(path) != originals[path][0]:
                raise InstallError("An installation file changed before completion. Try again.")
            if path in writes:
                published = _identity(stages[path])
                os.replace(stages[path], path)
            else:
                published = None
                path.unlink()
            changed.append((path, published))
    except BaseException as error:
        restored = True
        for path, published in reversed(changed):
            original, saved = originals[path]
            try:
                if _identity(path) != published:
                    restored = False
                    continue
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(saved, path)
            except (OSError, InstallError):
                # Keep recovery copies/journal if the filesystem cannot roll back.
                restored = False
        if restored:
            for _, saved in originals.values():
                saved.unlink(missing_ok=True)
            (backup / "restore.json").unlink(missing_ok=True)
            backup.rmdir()
        else:
            raise InstallError(
                f"Installation could not roll back completely. Recovery copies: {backup}"
            ) from error
        raise
    finally:
        for path in stages.values():
            path.unlink(missing_ok=True)
    kept = False
    for path, (original, saved) in originals.items():
        if saved.exists() and original is not None:
            if path in managed:
                saved.unlink()
            else:
                kept = True
    if not kept:
        (backup / "restore.json").unlink(missing_ok=True)
        backup.rmdir()
    return str(backup) if kept else ""


def install(layout, artifact, version, *, desktop=False, stop=None):
    stop = stop or threading.Event()
    _check_cancel(stop)
    _check_layout(layout)
    if not isinstance(version, str) or not 1 <= len(version) <= 100:
        raise InstallError("The application version is invalid.")
    if artifact.kind not in ("binary", "appimage") or not artifact.path.is_file():
        raise InstallError("Choose a packaged Linux binary or AppImage.")
    with artifact.path.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise InstallError("The source is not a Linux executable.")
    if not icon_path().is_file():
        raise InstallError("The application icon is missing from this build.")
    entry = desktop_entry(layout)
    layout.root.mkdir(parents=True, exist_ok=True)
    try:
        with database_save_lock(layout.binary, realm=False):
            previous = installation(layout)
            if previous is None and layout.binary.exists():
                raise InstallError(
                    "An unmanaged file already occupies the install location. "
                    "It was not overwritten."
                )
            writes = {
                layout.binary: artifact.path,
                layout.icon: icon_path(),
                layout.launcher: entry,
            }
            if desktop and layout.desktop:
                writes[layout.desktop] = entry
            files = {
                role: {
                    "path": str(path),
                    "sha256": _hash(content)
                    if isinstance(content, Path)
                    else hashlib.sha256(content).hexdigest(),
                }
                for role, path in layout.roles().items()
                if (content := writes.get(path)) is not None
            }
            if (
                previous
                and not desktop
                and "desktop" in previous["files"]
                and layout.desktop
                and previous["files"]["desktop"]["path"] == str(layout.desktop)
            ):
                files["desktop"] = previous["files"]["desktop"]
            record = {"owner": OWNER, "version": version, "kind": artifact.kind, "files": files}
            writes[layout.manifest] = (json.dumps(record, indent=2) + "\n").encode()
            managed = {layout.manifest}
            if previous:
                for role, row in previous["files"].items():
                    path = layout.roles().get(role)
                    if (
                        path
                        and row["path"] == str(path)
                        and path.is_file()
                        and (role == "binary" or _hash(path) == row["sha256"])
                    ):
                        managed.add(path)
            expected = {
                path: files[role]["sha256"]
                for role, path in layout.roles().items()
                if path in writes
            }
            backup = _transaction(layout, writes, [], stop, managed, expected)
    except PermissionError as error:
        raise InstallError(
            "The user folder is not writable or another installation/update is running. "
            "No administrator access is required."
        ) from error
    return {"path": str(layout.binary), "backup": backup, "kind": artifact.kind}


def uninstall(layout, *, stop=None):
    stop = stop or threading.Event()
    _check_cancel(stop)
    record = installation(layout)
    if record is None:
        return {"removed": [], "kept": [], "backup": ""}
    try:
        with database_save_lock(layout.binary, realm=False):
            record = installation(layout)
            if record is None:
                return {"removed": [], "kept": [], "backup": ""}
            remove, kept = [], []
            for role, row in record["files"].items():
                path = layout.roles().get(role)
                if path is None or row["path"] != str(path):
                    kept.append(row["path"])
                    continue
                if path.is_symlink():
                    kept.append(str(path))
                    continue
                if not path.exists():
                    continue
                # The binary can legitimately change through the built-in updater.
                if role != "binary" and _hash(path) != row["sha256"]:
                    kept.append(str(path))
                    continue
                if role == "binary":
                    with path.open("rb") as stream:
                        if stream.read(4) != b"\x7fELF":
                            kept.append(str(path))
                            continue
                remove.append(path)
            remove.append(layout.manifest)
            backup = _transaction(layout, {}, remove, stop, set(remove))
    except PermissionError as error:
        raise InstallError(
            "Another installation/update is running, or its files are not writable."
        ) from error
    return {"removed": [str(path) for path in remove], "kept": kept, "backup": backup}
