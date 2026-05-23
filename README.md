# Dock Export

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![QGIS](https://img.shields.io/badge/QGIS-3.22+-green)](https://www.qgis.org/)

A spec-driven export plugin for QGIS. Select layers once, configure everything in one place — names, formats, filters, CRS, styles, field subsets — and export to single files, GeoPackage, or portable archives. Never mutates live project layers.

---

## What problem does this solve?

Normally in QGIS, exporting layers means repeating the same steps over and over: right-click → Export → pick format → pick path → repeat. Need the same layer in three formats? Do it three times. Want to filter, reproject, and apply a style? That's more dialogs per layer. Have a project with 20 layers to share? Export them one by one or zip the project file and hope the file paths match.

Dock Export replaces all of that with a single dock:

- **Select layers once** — check what you need from one list
- **Configure everything in one place** — rename, filter, reproject, subset fields, apply styles per layer
- **Export in one click** — single files (multiple formats per layer), one multi-layer GeoPackage, or a fully self-contained archive (`.woof` / `.zip`) with rewritten project XML

It's a shortcut for: *I need to get data out of QGIS without busywork.*

---

## Features

### Export modes

| Mode | What it does | Best for |
|------|-------------|----------|
| **Single Files** | Each selected layer → one or more files in a directory (GPKG, Shapefile, GeoJSON, GeoTIFF, ...) | Delivering layers individually, converting formats, archiving in a folder structure |
| **GeoPackage** | All selected layers → a single `.gpkg` file with separate tables | Sharing many layers as one file, embedding in other projects |
| **Project Export** | Entire project → `.woof` archive or `.zip`, with all source files + rewritten project XML | Sending the whole project to someone, backup, moving between machines |

### Per-layer controls

- **Export name** — rename per layer independently of the source name; naming template with `{layer_name}`, `{date}`, `{crs}`, `{datetime}` placeholders
- **QGIS expression filter** — per-layer `WHERE` clause using `QgsExpression` (field list, function tree, search, validation)
- **CRS reprojection** — per-layer target CRS via native QGIS projection selector
- **Field subset** — choose which attributes to include per layer
- **Format override** — per-layer driver override (e.g. force a specific layer to Shapefile while the rest use GPKG)

### Vector formats

GPKG, ESRI Shapefile, GeoJSON, KML, CSV, FlatGeobuf, GPX, GML, TopoJSON, SQLite, SpatiaLite, Newline-delimited GeoJSON, DXF, DGN, MapInfo TAB, GeoParquet, Arrow, MBTiles, ESRI FileGDB, GeoRSS, XLSX, ODS.

### Raster formats

GeoTIFF, PNG, JPEG, JPEG2000, WebP, BMP, MBTiles, ERDAS Imagine.

### Style management

- **QML sidecars** — per-layer `.qml` files next to the export
- **SLD sidecars** — per-layer `.sld` files (vector only)
- **Embed in GPKG** — styles stored in the `layer_styles` table (works with Single Files GPKG and GeoPackage tab)

### Archive export (.woof / ZIP)

- **.woof (v2)** — Python implementation, zstd per-entry
- **.woof (v3)** — Rust native crate (`native_woof_impl`), xxhash3-64 integrity hashes, seek table for random access, zstd compression, parallel decompression
- **ZIP** — standard deflate compression via Python `zipfile`
- **Compression levels** — None / Normal / Heavy (maps to zstd levels 0 / 3 / 9)
- **Handles remote layers** — WMS, WFS, PostGIS, etc. keep their original datasource URLs in the project XML
- **Handles sidecars** — QML, SLD, world files (`.tfw`, `.pgw`, `.jgw`, ...) alongside source files are collected automatically
- **Project resources** — layout images, SVGs, HTML items, report templates are included
- **XML rewriting** — datasource paths in the project file are rewritten to archive-relative paths

### QGIS integration

- Docks inside the QGIS main window (not a modal dialog)
- Right-click any layer → opens Dock Export with that layer preselected
- `.woof` opener injected into Project → Open From submenu
- Auto-refresh when layers are added, removed, or renamed
- Settings persist across QGIS sessions via `QgsSettings`

---

## .woof Archive Format

`.woof` is a custom binary archive designed for packaging QGIS projects. It bundles source files, sidecars, project resources, and a rewritten `.qgs` project file into a single portable file.

| Version | Language | Hash | Structure | Pack speed | Notes |
|---------|----------|------|-----------|------------|-------|
| v2 | Python | BLAKE3 → xxhash3-64 | Flat: entry count + name heap + payload blob | ~400 MB/s (no-compress) | Reference implementation, no random access |
| v3 | Rust | xxhash3-64 | Seek table: sorted name heap, per-entry offset + hash + compressed/uncompressed size | ~650 MB/s (no-compress) | Random access via `unpack_one`, parallel decompression, integrity verification per entry |

Both versions use zstd compression per entry.

---

## Compatibility

- QGIS 3.22 – 4.99
- Qt5 / Qt6
- GDAL (bundled with QGIS)
- Python 3.10+
- Rust native crate requires `maturin build --release` (or use a pre-built wheel)

---

## License

GNU General Public License v3.0. See `LICENSE`.
