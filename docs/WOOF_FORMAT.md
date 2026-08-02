# .woof Format

A `.woof` file is a single-file snapshot of a QGIS project: every file the
project depends on (vector datasets, rasters, GeoPackages, styles, world
files, layout images, SVGs, report templates) plus the project file itself
with all paths rewritten to canonical `woof://` URIs.

Remote layers keep their original URLs. Scratch and memory layers are noted
as not packaged.

## Dual-path implementation

The format has two backend implementations that are 100% archive-compatible:

| Path | Language | Speed | Shipped in QGIS repo? | Features |
|---|---|---|---|---|
| **Default (Python)** | Python + `zstandard` | Moderate | Yes | v4 read/write, per-entry zstd, v2/v3/v4 compat, manifest |
| **Fast (Rust)** | Rust + PyO3 | 2-5x faster | No (optional install) | All of the above + seek table, dedup, xxhash3-64 checksums, parallel decompression |

Archives created by either backend can be read by the other. The Rust path
adds performance and integrity guarantees but is not required for basic
operation.

## Rust native module (optional performance upgrade)

The Rust crate (`woof_native/`) provides a native PyO3 module that
accelerates packing, unpacking, and random-access extraction. To install:

```bash
# From source (requires Rust toolchain)
cd woof_native
cargo build --release
cp target/release/_native_impl.{dll,pyd,so} ../dock_export/_woof_native/

# Or via pip (when available)
pip install woof-native
```

The plugin falls back to pure Python automatically if the native module is
absent.

## Manifest

Every `.woof` v4 archive contains a `woof-manifest.json` entry that records:

- Entry types (project, vector, raster, style, resource, arcpy, manifest)
- Dependency graph (companion files like `.shx`/`.dbf` for `.shp`)
- `woof://` URI rewrites for portable path resolution
- Per-entry hashes and sizes

## Content-addressed dedup (Rust only)

When the native module is active, identical content is stored once in the
archive payload. Multiple seek entries pointing to different names can
reference the same data if their xxhash3-64 hashes match. This is
transparent on extraction - the Python fallback reads deduplicated archives
correctly.
