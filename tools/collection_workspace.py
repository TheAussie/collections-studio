"""In-memory collection edits. Realm files are handled by the separate native backend."""

from copy import deepcopy
from uuid import uuid4

from tools.beatmap_downloads import valid_hash


class Workspace:
    def __init__(self, document, source_path):
        self.source_path = source_path
        self.source_hash = document["SourceRealmSha256"]
        self.format = document.get("Format", "realm")
        self.legacy_version = document.get("Version", 20261026)
        self.collections = deepcopy(document["Collections"])
        self.beatmaps = self._inventory_metadata(document.get("Beatmaps", {}))
        self.present_hashes = {
            checksum.lower()
            for checksum, details in self.beatmaps.items()
            if details.get("Available", True)
        }
        self.database_hashes = self.present_hashes.copy() if self.format == "realm" else set()
        # Remote imports may add metadata later; they must not become game inventory.
        self.library_hashes = (
            set(self.beatmaps) if self.format == "realm" else self.present_hashes.copy()
        )
        self.downloaded = {}
        self.library_source = document.get("LibrarySource")
        self._baseline = deepcopy(self.collections)
        self._undo = []

    @property
    def dirty(self):
        return self.collections != self._baseline

    @property
    def can_undo(self):
        return bool(self._undo)

    def collection(self, collection_id):
        return next(item for item in self.collections if item["Id"] == collection_id)

    def missing_hashes(self, collection_ids=None):
        return list(
            dict.fromkeys(
                checksum.lower()
                for item in self.collections
                if collection_ids is None or item["Id"] in collection_ids
                for checksum in item["Hashes"]
                if checksum.lower() not in self.present_hashes
            )
        )

    def _remember(self):
        self._undo.append(deepcopy(self.collections))

    def undo(self):
        if self._undo:
            self.collections = self._undo.pop()

    def create(self, name):
        self._check_name(name)
        self._remember()
        item = {"Id": str(uuid4()), "Name": name, "Hashes": []}
        self.collections.append(item)
        return item["Id"]

    def rename(self, collection_id, name):
        self._check_name(name, collection_id)
        item = self.collection(collection_id)
        if item["Name"] != name:
            self._remember()
            item["Name"] = name

    def _check_name(self, name, collection_id=None):
        if not name or not name.strip() or "\x00" in name:
            raise ValueError("Enter a collection name without null characters.")
        if any(item["Name"] == name and item["Id"] != collection_id for item in self.collections):
            raise ValueError("A collection with this exact name already exists.")

    def delete(self, collection_id):
        self.collection(collection_id)
        self._remember()
        self.collections = [item for item in self.collections if item["Id"] != collection_id]

    def remove_maps(self, collection_id, hashes):
        hashes = {value.lower() for value in hashes}
        item = self.collection(collection_id)
        remaining = [value for value in item["Hashes"] if value.lower() not in hashes]
        if remaining != item["Hashes"]:
            self._remember()
            item["Hashes"] = remaining

    @staticmethod
    def _inventory_metadata(maps):
        result = {}
        for value, details in maps.items():
            if valid_hash(value):
                key = value.lower()
                if key not in result or details.get("Available", True):
                    result[key] = dict(details)
        return result

    @staticmethod
    def _selected_hashes(hashes):
        values = list(hashes)
        if not values or any(not valid_hash(value) for value in values):
            raise ValueError("Select one or more valid beatmap MD5s.")
        return list(dict.fromkeys(value.lower() for value in values))

    def _require_collection(self, collection_id):
        try:
            return self.collection(collection_id)
        except StopIteration:
            raise ValueError(
                "The collection changed. Choose it again before adding maps."
            ) from None

    def _addition(self, target, selected):
        known = {value.lower() for value in target["Hashes"]}
        additions = [value for value in selected if value not in known]
        return additions, {
            "selected": len(selected),
            "added": len(additions),
            "already_present": len(selected) - len(additions),
            "removed": 0,
        }

    def transfer_maps(self, source_id, target_id, hashes, *, move=False):
        """One atomic, undoable union; moves remove only selected source memberships."""
        selected = self._selected_hashes(hashes)
        selected_set = set(selected)
        source, target = self._require_collection(source_id), self._require_collection(target_id)
        known_source = {value.lower() for value in source["Hashes"]}
        if not selected_set <= known_source:
            raise ValueError(
                "Some selected maps are no longer in the source collection. Select them again."
            )
        additions, report = self._addition(target, selected)
        if source is target:
            return {**report, "added": 0, "already_present": len(selected)}
        if additions or move:
            remaining = (
                [value for value in source["Hashes"] if value.lower() not in selected_set]
                if move
                else None
            )
            self._remember()
            target["Hashes"] = [*target["Hashes"], *additions]
            if move:
                source["Hashes"] = remaining
                report["removed"] = len(selected)
        return report

    def add_library_maps(self, target_id, hashes):
        selected = self._selected_hashes(hashes)
        target = self._require_collection(target_id)
        if not set(selected) <= self.library_hashes:
            raise ValueError(
                "Some selected maps are no longer in the loaded game library. Browse it again."
            )
        additions, report = self._addition(target, selected)
        if additions:
            self._remember()
            target["Hashes"] = [*target["Hashes"], *additions]
        return report

    def load_inventory(self, document):
        maps = self._inventory_metadata(document["Beatmaps"])
        self.beatmaps.update(maps)
        self.present_hashes = self.database_hashes | {
            value for value, details in maps.items() if details.get("Available", True)
        }
        self.library_hashes = set(self.beatmaps) if self.format == "realm" else set(maps)

    def merge(self, incoming):
        proposed = deepcopy(self.collections)
        created = added = 0
        for group in incoming:
            matches = [item for item in proposed if item["Name"] == group["Name"]]
            if len(matches) > 1:
                raise ValueError(
                    "More than one existing collection has an incoming name. Rename or delete "
                    "the duplicate collections before importing."
                )
            if matches:
                target = matches[0]
            else:
                target = {"Id": str(uuid4()), "Name": group["Name"], "Hashes": []}
                proposed.append(target)
                created += 1
            known = {value.lower() for value in target["Hashes"]}
            for value in group["Hashes"]:
                value = value.lower()
                if value not in known:
                    known.add(value)
                    target["Hashes"].append(value)
                    added += 1
        if proposed != self.collections:
            self._remember()
            self.collections = proposed
        return created, added

    def plan(self):
        return {"SourceRealmSha256": self.source_hash, "Collections": deepcopy(self.collections)}

    def summary(self):
        before = {item["Id"]: item for item in self._baseline}
        after = {item["Id"]: item for item in self.collections}
        created = len(after.keys() - before.keys())
        deleted = len(before.keys() - after.keys())
        edited = sum(before[key] != after[key] for key in before.keys() & after.keys())
        return created, edited, deleted

    def mark_saved(self, source_path, source_hash):
        self.source_path = source_path
        self.source_hash = source_hash
        self._baseline = deepcopy(self.collections)
        self._undo.clear()
