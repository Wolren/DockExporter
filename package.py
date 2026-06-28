#!/usr/bin/env python3
"""Build the plugin zip for distribution."""

import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def get_plugin_dir() -> str:
    """Find the plugin directory (the one with metadata.txt)."""
    for child in ROOT.iterdir():
        if child.is_dir() and (child / "metadata.txt").exists():
            return child.name
    raise FileNotFoundError("No plugin directory with metadata.txt found")


def get_version(plugin_dir: str) -> str:
    meta = ROOT / plugin_dir / "metadata.txt"
    m = re.search(r"^version=(.+)", meta.read_text(), re.M)
    return m.group(1).strip() if m else "0.0.0"


def build():
    plugin = get_plugin_dir()
    version = get_version(plugin)
    zip_name = ROOT / f"{plugin}-{version}.zip"

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        src = ROOT / plugin
        for path in sorted(src.rglob("*")):
            rel = path.relative_to(src)
            parts = rel.parts
            if any(p.startswith(".") or p == "__pycache__" for p in parts):
                continue
            if path.is_file():
                zf.write(path, f"{plugin}/{rel}")

    size = os.path.getsize(zip_name)
    print(f"Built: {zip_name.name}  ({size / 1024:.0f} KB)")
    return zip_name.name


if __name__ == "__main__":
    build()
