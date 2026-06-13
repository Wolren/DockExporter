"""Utility functions with no QGIS dependency — testable with plain Python."""

from __future__ import annotations

import os

_SIDECAR_EXTS = frozenset(
    {".qml", ".sld", ".tfw", ".pgw", ".jgw", ".gw", ".wld", ".aux.xml"},
)


def collect_sidecar_files(file_paths: list[str]) -> list[str]:
    """Return companion files (QML, SLD, world files) found alongside source paths."""
    found: list[str] = []
    seen = set(file_paths)
    for fp in file_paths:
        base, _ = os.path.splitext(fp)
        for ext in _SIDECAR_EXTS:
            companion = base + ext
            if os.path.isfile(companion) and companion not in seen:
                found.append(companion)
                seen.add(companion)
    return found
