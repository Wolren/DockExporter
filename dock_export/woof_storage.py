"""QgsProjectStorage for opening .woof archives directly as QGIS projects.

.woof is a custom binary format (not ZIP). On open, extracts the archive
to a persistent directory alongside the .woof file, then loads project.qgs."""

from __future__ import annotations

import logging
import os

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import QgsProject

from .woof_format import extract_woof_to_directory

logger = logging.getLogger("DockExport.WoofStorage")


def _extract_dir_for(woof_path: str) -> str:
    base = os.path.splitext(woof_path)[0]
    return base + "_files"


def extract_woof(woof_path: str, target_dir: str = None) -> str | None:
    """Extract a .woof archive and return the path to the .qgs inside.

    If target_dir is None, extracts alongside the .woof.
    Returns path to project.qgs, or None on failure.
    """
    if not os.path.isfile(woof_path):
        return None

    if target_dir is None:
        target_dir = _extract_dir_for(woof_path)

    try:
        with open(woof_path, "rb") as f:
            data = f.read()
        extract_woof_to_directory(data, target_dir)
    except Exception as e:
        logger.error("Failed to extract .woof: %s", e)
        return None

    qgs_path = os.path.join(target_dir, "project.qgs")
    return qgs_path if os.path.isfile(qgs_path) else None


def open_woof_project(woof_path: str) -> bool:
    """Open a .woof file as a QGIS project.

    Extracts to a persistent directory alongside the .woof, then opens
    the project.qgs from there.
    """
    target_dir = _extract_dir_for(woof_path)
    qgs_path = extract_woof(woof_path, target_dir)
    if qgs_path is None:
        return False

    proj = QgsProject.instance()
    return proj.read(qgs_path)
