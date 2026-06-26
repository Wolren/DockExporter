from __future__ import annotations

import logging
import os

from qgis.core import QgsProject

from .manifest import (
    Manifest,
    _MANIFEST_ENTRY_NAME,
    from_woof_uri,
)
from .woof import extract_woof_to_directory, unpack_one

logger = logging.getLogger("DockExport.WoofStorage")


def _extract_dir_for(woof_path: str) -> str:
    base = os.path.splitext(woof_path)[0]
    return base + "_files"


def _read_manifest(data: bytes) -> Manifest | None:
    try:
        manifest_json = unpack_one(data, _MANIFEST_ENTRY_NAME)
        return Manifest.from_json(manifest_json.decode("utf-8"))
    except (KeyError, Exception) as exc:
        logger.debug("No manifest in .woof archive: %s", exc)
        return None


def _rewrite_woof_uris_in_qgs(qgs_path: str, target_dir: str, uri_rewrites: dict[str, str]) -> None:
    """Replace woof:// URIs back to absolute filesystem paths in the extracted project file."""
    with open(qgs_path, encoding="utf-8") as f:
        xml = f.read()

    rel_map: dict[str, str] = {}
    for woof_uri, _orig_path in uri_rewrites.items():
        arcname = from_woof_uri(woof_uri)
        if arcname:
            dst = os.path.join(target_dir, arcname)
            rel_map[woof_uri] = dst.replace("\\", "/")

    for woof_uri, dst_path in rel_map.items():
        xml = xml.replace(woof_uri, dst_path)

    xml = xml.replace(
        '<Relative type="int">2</Relative>',
        '<Relative type="int">0</Relative>',
    )

    with open(qgs_path, "w", encoding="utf-8") as f:
        f.write(xml)


def extract_woof(woof_path: str, target_dir: str | None = None) -> str | None:
    if not os.path.isfile(woof_path):
        return None

    if target_dir is None:
        target_dir = _extract_dir_for(woof_path)

    try:
        with open(woof_path, "rb") as f:
            data = f.read()

        manifest = _read_manifest(data)

        extract_woof_to_directory(data, target_dir)

        qgs_path = os.path.join(target_dir, "project.qgs")
        if manifest and os.path.isfile(qgs_path) and manifest.uri_rewrites:
            _rewrite_woof_uris_in_qgs(qgs_path, target_dir, manifest.uri_rewrites)

    except Exception:
        logger.exception("Failed to extract .woof")
        return None

    qgs_path = os.path.join(target_dir, "project.qgs")
    return qgs_path if os.path.isfile(qgs_path) else None


def open_woof_project(woof_path: str) -> bool:
    target_dir = _extract_dir_for(woof_path)
    qgs_path = extract_woof(woof_path, target_dir)
    if qgs_path is None:
        return False

    proj = QgsProject.instance()
    return proj.read(qgs_path)
