"""Read stable's cached beatmap metadata, including the January 2025 float change."""

import os
import struct
from pathlib import Path

from tools.beatmap_downloads import mode_name, valid_hash


class Reader:
    def __init__(self, stream, size):
        self.stream, self.size = stream, size

    def take(self, count):
        if count < 0 or self.stream.tell() + count > self.size:
            raise ValueError("osu!.db is truncated or has an unsupported layout.")
        data = self.stream.read(count)
        if len(data) != count:
            raise ValueError("osu!.db changed while reading.")
        return data

    def skip(self, count):
        if count < 0 or self.stream.tell() + count > self.size:
            raise ValueError("osu!.db contains an invalid field length.")
        self.stream.seek(count, os.SEEK_CUR)

    def integer(self):
        return struct.unpack("<i", self.take(4))[0]

    def count(self, maximum):
        count = self.integer()
        if not 0 <= count <= maximum:
            raise ValueError("osu!.db contains an invalid record count.")
        return count

    def string(self):
        marker = self.take(1)[0]
        if marker == 0:
            return ""
        if marker != 11:
            raise ValueError("osu!.db contains an invalid string marker.")
        length = 0
        for shift in range(0, 35, 7):
            value = self.take(1)[0]
            if shift == 28 and value > 15:
                raise ValueError("Invalid osu!.db string length.")
            length |= (value & 127) << shift
            if value < 128:
                break
        else:
            raise ValueError("Invalid osu!.db string length.")
        if length > 1024 * 1024:
            raise ValueError("An osu!.db string exceeds 1 MiB.")
        try:
            return self.take(length).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 in osu!.db.") from error


def read_osu_database(path):
    with Path(path).open("rb", buffering=256 * 1024) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > 1024 * 1024 * 1024:
            raise ValueError("osu!.db exceeds 1 GiB.")
        reader = Reader(stream, before.st_size)
        version = reader.integer()
        if not 20080101 <= version <= 99991231:
            raise ValueError("Unsupported osu!.db version.")
        reader.count(10_000_000)  # Folder count.
        reader.skip(9)  # Account flag and unlock time; account data is not retained.
        reader.string()  # Player name is not retained.
        count = reader.count(2_000_000)
        maps, invalid = {}, 0
        for _ in range(count):
            entry_size = reader.count(16 * 1024 * 1024) if version < 20191106 else None
            start = stream.tell()
            artist = reader.string()
            reader.string()  # Unicode artist.
            title = reader.string()
            reader.string()  # Unicode title.
            reader.string()  # Creator.
            difficulty = reader.string()
            reader.string()  # Audio filename.
            checksum = reader.string()
            filename = reader.string()
            reader.skip(1 + 6 + 8)  # Status, object counts, last modification time.
            reader.skip(4 if version < 20140609 else 16)  # AR/CS/HP/OD.
            reader.skip(8)  # Slider velocity.
            if version >= 20140609:
                for _mode in range(4):
                    # Int-double pairs became int-float pairs in database version 20250107.
                    for _rating in range(reader.count(100_000)):
                        if reader.take(1) != b"\x08":
                            raise ValueError("Invalid osu!.db star-rating key marker.")
                        reader.skip(4)
                        marker = b"\x0c" if version >= 20250107 else b"\x0d"
                        if reader.take(1) != marker:
                            raise ValueError("Unsupported osu!.db star-rating value marker.")
                        reader.skip(4 if version >= 20250107 else 8)
            reader.skip(12)  # Drain time, total time, preview offset.
            reader.skip(reader.count(1_000_000) * 17)  # Timing points.
            beatmap_id, set_id = reader.integer(), reader.integer()
            reader.skip(4 + 4 + 2 + 4)  # Thread ID, four grades, local offset, stack leniency.
            mode = reader.take(1)[0]
            reader.string()  # Source.
            reader.string()  # Tags.
            reader.skip(2)
            reader.string()  # Title font.
            reader.skip(1 + 8 + 1)
            folder = reader.string()
            reader.skip(8 + 5)
            if version < 20140609:
                reader.skip(2)
            reader.skip(4 + 1)
            if entry_size is not None and entry_size not in (
                stream.tell() - start,
                stream.tell() - start + 4,
            ):
                raise ValueError("osu!.db entry size does not match its decoded fields.")
            if valid_hash(checksum):
                maps[checksum.lower()] = {
                    "Title": title,
                    "Artist": artist,
                    "Difficulty": difficulty,
                    "Mode": mode_name(mode),
                    "BeatmapId": beatmap_id,
                    "SetId": set_id,
                    "Filename": filename,
                    "Folder": folder,
                    "Available": True,
                }
            else:
                invalid += 1
        reader.skip(4)  # Permissions; intentionally ignored.
        if stream.tell() != before.st_size:
            raise ValueError("Unexpected trailing bytes in osu!.db; use the Songs scan instead.")
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("osu!.db changed while reading. Close stable and try again.")
    return {"Beatmaps": maps, "Scanned": count, "ErrorCount": invalid, "Version": version}
