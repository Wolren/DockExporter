from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Literal

EntryType = Literal["project", "vector", "raster", "style", "resource", "arcpy", "manifest"]


@dataclasses.dataclass
class ManifestEntry:
    type: EntryType
    size: int
    hash: str


@dataclasses.dataclass
class Manifest:
    woof_version: int
    created: str
    plugin_version: str
    entries: dict[str, ManifestEntry]
    dependencies: dict[str, list[str]]
    uri_rewrites: dict[str, str]

    def to_json(self) -> str:
        d = {
            "woof_version": self.woof_version,
            "created": self.created,
            "plugin_version": self.plugin_version,
            "entries": {k: dataclasses.asdict(v) for k, v in self.entries.items()},
            "dependencies": self.dependencies,
            "uri_rewrites": self.uri_rewrites,
        }
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, s: str) -> Manifest:
        d = json.loads(s)
        entries = {k: ManifestEntry(**v) for k, v in d["entries"].items()}
        return cls(
            woof_version=d["woof_version"],
            created=d["created"],
            plugin_version=d["plugin_version"],
            entries=entries,
            dependencies=d.get("dependencies", {}),
            uri_rewrites=d.get("uri_rewrites", {}),
        )

    @classmethod
    def empty(cls) -> Manifest:
        return cls(
            woof_version=4,
            created=datetime.now(timezone.utc).isoformat(),
            plugin_version="",
            entries={},
            dependencies={},
            uri_rewrites={},
        )


_MANIFEST_ENTRY_NAME = "woof-manifest.json"
WOOF_URI_PREFIX = "woof://"


def to_woof_uri(arcname: str) -> str:
    return f"{WOOF_URI_PREFIX}{arcname}"


def from_woof_uri(uri: str) -> str | None:
    if uri.startswith(WOOF_URI_PREFIX):
        return uri[len(WOOF_URI_PREFIX) :]
    return None


def build_manifest(
    entries: dict[str, bytes],
    path_map: dict[str, str] | None = None,
    plugin_version: str = "",
    dependencies: dict[str, list[str]] | None = None,
) -> Manifest:
    manifest_entries: dict[str, ManifestEntry] = {}
    uri_rewrites: dict[str, str] = {}

    for arcname, content in entries.items():
        entry_type: EntryType = "resource"
        if arcname == "project.qgs":
            entry_type = "project"
        elif arcname == "woof-manifest.json":
            entry_type = "manifest"
        elif arcname == "layer_tree.json" or arcname == "open_in_arcgis_pro.py":
            entry_type = "arcpy"
        elif arcname.startswith("vectors/") or arcname.startswith("vector/"):
            entry_type = "vector"
        elif arcname.startswith("rasters/") or arcname.startswith("raster/"):
            entry_type = "raster"
        elif arcname.endswith(".qml") or arcname.endswith(".sld"):
            entry_type = "style"

        h = _fast_hash(content)
        manifest_entries[arcname] = ManifestEntry(
            type=entry_type,
            size=len(content),
            hash=h,
        )

        if path_map:
            for orig_path, mapped_arcname in path_map.items():
                if mapped_arcname == arcname:
                    uri = to_woof_uri(arcname)
                    uri_rewrites[uri] = orig_path

    return Manifest(
        woof_version=4,
        created=datetime.now(timezone.utc).isoformat(),
        plugin_version=plugin_version,
        entries=manifest_entries,
        dependencies=dependencies or {},
        uri_rewrites=uri_rewrites,
    )


def _fast_hash(data: bytes) -> str:
    try:
        import xxhash

        return xxhash.xxh3_64_hexdigest(data)
    except ImportError:
        import hashlib

        return hashlib.sha256(data).hexdigest()[:16]
