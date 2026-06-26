#!/usr/bin/env python3
"""Package the plugin for distribution.

Modes:
  pure   — QGIS official repository zip (excludes native Rust binaries)
  full   — Combined zip with native Rust shims for the current platform
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(ROOT, "dock_export")
DIST_DIR = os.path.join(ROOT, "dist")

EXCLUDE_PATTERNS_PURE = [
    re.compile(r"__pycache__"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.pyd$"),
    re.compile(r"\.so$"),
    re.compile(r"\.dylib$"),
    re.compile(r"\.dll$"),
    re.compile(r"\.git"),
    re.compile(r"\.woof$"),
    re.compile(r"\.qgs$"),
    re.compile(r"\.bak$"),
    re.compile(r"^_woof_native"),  # no native binaries in QGIS zip
]

EXCLUDE_PATTERNS_FULL = [
    re.compile(r"__pycache__"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.git"),
    re.compile(r"\.woof$"),
    re.compile(r"\.qgs$"),
    re.compile(r"\.bak$"),
]


def _should_include(relpath: str, patterns: list) -> bool:
    return not any(p.search(relpath) for p in patterns)


def _walk_and_write(zf: zipfile.ZipFile, exclude_patterns: list) -> int:
    """Walk PLUGIN_DIR and add files to zip. Returns count of files added."""
    count = 0
    for root, dirs, files in os.walk(PLUGIN_DIR):
        dirs[:] = [d for d in dirs if _should_include(os.path.join(root, d), exclude_patterns)]
        for fn in files:
            fpath = os.path.join(root, fn)
            rel = os.path.relpath(fpath, ROOT)
            if _should_include(rel, exclude_patterns):
                zf.write(fpath, rel)
                count += 1
    return count


def package_pure() -> str:
    """Package pure-Python plugin zip (no native binaries)."""
    os.makedirs(DIST_DIR, exist_ok=True)
    zip_path = os.path.join(DIST_DIR, "dock_export.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _walk_and_write(zf, EXCLUDE_PATTERNS_PURE)

    size = os.path.getsize(zip_path)
    print(f"Pure-Python: {zip_path} ({size:,} bytes, {n} files)")
    return zip_path


def package_full() -> str:
    """Package plugin zip including any native Rust shims present."""
    os.makedirs(DIST_DIR, exist_ok=True)
    zip_path = os.path.join(DIST_DIR, "dock_export-full.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        n = _walk_and_write(zf, EXCLUDE_PATTERNS_FULL)

    size = os.path.getsize(zip_path)
    print(f"Full (with native): {zip_path} ({size:,} bytes, {n} files)")
    return zip_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package plugin for distribution")
    parser.add_argument(
        "--mode",
        choices=["pure", "full", "both"],
        default="pure",
        help="Which package to build (default: pure)",
    )
    args = parser.parse_args()

    if args.mode == "pure":
        package_pure()
    elif args.mode == "full":
        package_full()
    else:
        package_pure()
        package_full()
