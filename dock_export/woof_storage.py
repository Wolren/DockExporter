"""Open .woof archives directly as QGIS projects. Extracts to a persistent directory alongside the archive."""

from __future__ import annotations

import logging
import os

from qgis.core import QgsProject

from .woof import extract_woof_to_directory

logger = logging.getLogger("DockExport.WoofStorage")


def _extract_dir_for(woof_path: str) -> str:
    """Return the persistent extraction directory alongside a .woof file."""
    base = os.path.splitext(woof_path)[0]
    return base + "_files"


def extract_woof(woof_path: str, target_dir: str | None = None) -> str | None:
    """Extract a .woof archive and return the path to project.qgs, or None on failure."""
    if not os.path.isfile(woof_path):
        return None

    if target_dir is None:
        target_dir = _extract_dir_for(woof_path)

    try:
        with open(woof_path, "rb") as f:
            data = f.read()
        extract_woof_to_directory(data, target_dir)
    except Exception:
        logger.exception("Failed to extract .woof")
        return None

    qgs_path = os.path.join(target_dir, "project.qgs")
    return qgs_path if os.path.isfile(qgs_path) else None


def open_woof_project(woof_path: str) -> bool:
    """Open a .woof file as a QGIS project. Extracts, then loads project.qgs."""
    target_dir = _extract_dir_for(woof_path)
    qgs_path = extract_woof(woof_path, target_dir)
    if qgs_path is None:
        return False

    proj = QgsProject.instance()
    return proj.read(qgs_path)
