"""Generate realistic QGIS-like test data for .woof compressor benchmarks & tests."""

from __future__ import annotations

import os
import random

# ── Helpers ──────────────────────────────────────────────────────

_SYMBOL_COLORS = [
    "#ff0000",
    "#00ff00",
    "#0000ff",
    "#ffff00",
    "#ff00ff",
    "#00ffff",
    "#800000",
    "#008000",
    "#000080",
    "#808000",
]
_SYMBOL_NAMES = [
    "red_fill",
    "green_fill",
    "blue_fill",
    "yellow_fill",
    "magenta_fill",
    "cyan_fill",
    "maroon_fill",
    "dark_green",
    "navy_fill",
    "olive_fill",
    "dashed_red",
    "dashed_blue",
    "dotted_black",
    "hatch_fill",
    "gradient_fill",
    "outline_red_2pt",
    "outline_blue_1pt",
    "marker_circle_red",
    "marker_square_blue",
    "marker_triangle_green",
]
_COLORRAMP_NAMES = ["spectral", "viridis", "coolwarm", "rdbu", "blues"]
_EXPRESSION_NAMES = [
    "centroid_x",
    "centroid_y",
    "area_ha",
    "length_m",
    "label_case",
    "category_bucket",
    "rotation_from_azimuth",
]


def _make_symbol_xml(name: str, color: str) -> str:
    return (
        f'<symbol name="{name}" type="fill" force_rhr="0" '
        f'alpha="1" clip_to_extent="1">\n'
        f'  <layer pass="0" class="SimpleFill" locked="0">\n'
        f'    <prop k="color" v="{color}"/>\n'
        f'    <prop k="outline_color" v="{color}"/>\n'
        f'    <prop k="outline_width" v="0.26"/>\n'
        f"    <data_defined_properties>\n"
        f'      <Option type="Map">\n'
        f'        <Option name="name" type="QString" value=""/>\n'
        f'        <Option name="properties"/>\n'
        f'        <Option name="type" value="collection"/>\n'
        f"      </Option>\n"
        f"    </data_defined_properties>\n"
        f"  </layer>\n"
        f"</symbol>"
    )


def _make_colorramp_xml(name: str) -> str:
    return (
        f'<colorramp name="{name}" type="gradient">\n'
        f'  <prop k="color1" v="255,255,255,255"/>\n'
        f'  <prop k="color2" v="0,0,0,255"/>\n'
        f'  <prop k="stops" v="0.25;255,0,0,255:0.5;0,255,0,255:0.75;0,0,255,255"/>\n'
        f"</colorramp>"
    )


def _make_expression_xml(name: str) -> str:
    formulas = {
        "centroid_x": "$x",
        "centroid_y": "$y",
        "area_ha": "$area / 10000",
        "length_m": "$length",
        "label_case": "CASE WHEN \"type\" = 'A' THEN 'Alpha' ELSE 'Beta' END",
        "category_bucket": 'floor("value" / 100) * 100',
        "rotation_from_azimuth": "degrees(azimuth($geometry))",
    }
    expr = formulas.get(name, '"dummy"')
    return f'<expression name="{name}">\n  {expr}\n</expression>'


def _make_pipe_xml(
    symbol_refs: list[str],
    ramp_refs: list[str],
    expr_refs: list[str],
) -> str:
    """Generate a QGIS pipe/renderer XML referencing existing resources."""
    lines = ["<pipe>"]
    for s in symbol_refs:
        lines.append(f'  <res_ref name="{s}"/>')
    for r in ramp_refs:
        lines.append(f'  <res_ref name="{r}"/>')
    for e in expr_refs:
        lines.append(f'  <res_ref name="{e}"/>')
    lines.append("</pipe>")
    return "\n".join(lines)


# ── Public generation API ────────────────────────────────────────


def generate_qgs_project(
    num_layers: int = 5,
    shared_symbols: int = 3,
    shared_ramps: int = 2,
    shared_exprs: int = 2,
) -> str:
    """Generate a realistic .qgs project XML.

    Args:
        num_layers: How many layers (each gets 1-3 symbols + ramps)
        shared_symbols: How many symbols are shared across all layers
        shared_ramps: How many colorramps are shared
        shared_exprs: How many expressions are shared

    Returns:
        Complete .qgs XML string.

    """
    rng = random.Random(42)

    # Shared resources (reused across layers)
    symbols_xml = []
    ramp_xml = []
    expr_xml = []

    for i in range(shared_symbols):
        name = _SYMBOL_NAMES[i % len(_SYMBOL_NAMES)]
        color = _SYMBOL_COLORS[i % len(_SYMBOL_COLORS)]
        symbols_xml.append(_make_symbol_xml(f"shared_{name}", color))

    for i in range(shared_ramps):
        ramp_xml.append(_make_colorramp_xml(_COLORRAMP_NAMES[i]))

    for i in range(shared_exprs):
        expr_xml.append(_make_expression_xml(_EXPRESSION_NAMES[i]))

    # Per-layer unique resources
    layer_xmls = []
    for layer_id in range(num_layers):
        n_sym = rng.randint(1, 3)
        n_ramp = rng.randint(0, 1)
        n_expr = rng.randint(0, 1)

        sym_refs = [f"layer{layer_id}_sym{i}" for i in range(n_sym)]
        ramp_refs = [f"layer{layer_id}_ramp{i}" for i in range(n_ramp)]
        expr_refs = [f"layer{layer_id}_expr{i}" for i in range(n_expr)]

        # Unique symbols for this layer
        for i in range(n_sym):
            name = _SYMBOL_NAMES[(layer_id + i + shared_symbols) % len(_SYMBOL_NAMES)]
            color = _SYMBOL_COLORS[(layer_id + i) % len(_SYMBOL_COLORS)]
            symbols_xml.append(_make_symbol_xml(sym_refs[i], color))

        for i in range(n_ramp):
            ramp_xml.append(_make_colorramp_xml(ramp_refs[i]))

        for i in range(n_expr):
            expr_xml.append(_make_expression_xml(expr_refs[i]))

        layer_xmls.append(
            f"<maplayer>\n"
            f"  <id>layer_{layer_id}</id>\n"
            f"  <name>Layer {layer_id}</name>\n"
            f"  {_make_pipe_xml(sym_refs, ramp_refs, expr_refs)}\n"
            f"</maplayer>",
        )

    symbols_block = "\n".join(f"  {x}" for x in symbols_xml)
    ramps_block = "\n".join(f"  {x}" for x in ramp_xml)
    exprs_block = "\n".join(f"  {x}" for x in expr_xml)
    layers_block = "\n".join(layer_xmls)

    return (
        '<qgis version="3.40">\n'
        "  <project>\n"
        "    <title>Test Project</title>\n"
        f"    <symbols>\n{symbols_block}\n    </symbols>\n"
        f"    <colorramps>\n{ramps_block}\n    </colorramps>\n"
        f"    <expressions>\n{exprs_block}\n    </expressions>\n"
        f"    <layers>\n{layers_block}\n    </layers>\n"
        "  </project>\n"
        "</qgis>"
    )


def generate_qml_style(num_symbols: int = 3) -> str:
    """Generate a .qml style file with symbols."""
    rng = random.Random(num_symbols)
    syms = []
    for i in range(num_symbols):
        color = _SYMBOL_COLORS[rng.randint(0, len(_SYMBOL_COLORS) - 1)]
        syms.append(_make_symbol_xml(f"style_sym_{i}", color))
    sym_block = "\n".join(f"  {s}" for s in syms)
    return f'<qgis styleVersion="2">\n  <symbols>\n{sym_block}\n  </symbols>\n</qgis>'


def generate_geojson(num_features: int = 10) -> str:
    """Generate a GeoJSON FeatureCollection."""
    rng = random.Random(num_features)
    features = []
    for i in range(num_features):
        x = round(rng.uniform(-180, 180), 6)
        y = round(rng.uniform(-90, 90), 6)
        val = round(rng.uniform(0, 1000), 2)
        features.append(
            '{ "type": "Feature", "geometry": {'
            f'"type": "Point", "coordinates": [{x}, {y}]'
            '}, "properties": {'
            f'"id": {i}, "value": {val}, '
            f'"name": "feature_{i}"'
            "} }",
        )
    return (
        '{\n"type": "FeatureCollection",\n"features": [\n'
        + ",\n".join(features)
        + "\n]\n}"
    )


def generate_binary_blob(size_kb: int = 64) -> bytes:
    """Generate a pseudo-random binary blob simulating compressed GIS data."""
    rng = random.Random(size_kb)
    return bytes(rng.getrandbits(8) for _ in range(size_kb * 1024))


def generate_csv(num_rows: int = 50) -> str:
    """Generate a CSV file."""
    rng = random.Random(num_rows)
    rows = ["id,name,value,category"]
    for i in range(num_rows):
        name = f"item_{i}"
        val = rng.randint(0, 1000)
        cat = chr(ord("A") + rng.randint(0, 5))
        rows.append(f"{i},{name},{val},{cat}")
    return "\n".join(rows)


# ── Pre-built test suites ────────────────────────────────────────


def make_standard_test_set() -> dict[str, bytes]:
    """Create a standard dict of entries simulating a typical GIS project.

    Returns a dict mapping arcname → content (bytes) suitable for pack_woof().
    """
    entries: dict[str, bytes] = {}

    # Projects
    entries["project.qgs"] = generate_qgs_project(
        num_layers=8,
        shared_symbols=4,
        shared_ramps=3,
        shared_exprs=2,
    ).encode("utf-8")

    entries["subdir/second_project.qgs"] = generate_qgs_project(
        num_layers=3,
        shared_symbols=2,
        shared_ramps=1,
        shared_exprs=1,
    ).encode("utf-8")

    # Styles (shared symbols with projects above)
    entries["styles/roads.qml"] = generate_qml_style(4).encode("utf-8")
    entries["styles/parcels.qml"] = generate_qml_style(3).encode("utf-8")
    entries["styles/hydro.qml"] = generate_qml_style(5).encode("utf-8")

    # GeoJSON
    entries["data/points.geojson"] = generate_geojson(100).encode("utf-8")
    entries["data/polygons.geojson"] = generate_geojson(50).encode("utf-8")
    entries["data/lines.geojson"] = generate_geojson(75).encode("utf-8")

    # CSV
    entries["data/attributes.csv"] = generate_csv(200).encode("utf-8")

    # Binary files (simulating existing compressed GIS formats)
    entries["rasters/ortho.tiff"] = generate_binary_blob(256)
    entries["rasters/dem.tiff"] = generate_binary_blob(128)
    entries["vectors/roads.gpkg"] = generate_binary_blob(512)
    entries["vectors/parcels.gpkg"] = generate_binary_blob(1024)
    entries["vectors/hydro.gpkg"] = generate_binary_blob(64)

    # Small aux files
    entries["project.qgs.prj"] = b"WGS 84"
    entries["metadata.xml"] = (
        b"<metadata>\n"
        b"  <title>Test GIS Dataset</title>\n"
        b"  <date>2026-05-21</date>\n"
        b"  <abstract>A comprehensive test dataset for .woof compressor.</abstract>\n"
        b"</metadata>"
    )

    return entries


def make_colossal_test_set(
    num_qgs: int = 5,
    num_styles: int = 10,
    num_geojson: int = 10,
    num_binaries: list[int] | None = None,
    shared_symbols: int = 8,
) -> dict[str, bytes]:
    """Create a large test set for heavy benchmarks.

    Many projects share symbols via XML content similarity to stress-test dedup.
    """
    if num_binaries is None:
        num_binaries = [64, 256, 1024, 4096]
    entries: dict[str, bytes] = {}

    # Shared symbol templates (same content reused across many files)
    for i in range(num_qgs):
        entries[f"projects/project_{i:04d}.qgs"] = generate_qgs_project(
            num_layers=12,
            shared_symbols=shared_symbols,
            shared_ramps=5,
            shared_exprs=3,
        ).encode("utf-8")

    for i in range(num_styles):
        entries[f"styles/style_{i:04d}.qml"] = generate_qml_style(6).encode("utf-8")

    for i in range(num_geojson):
        entries[f"data/features_{i:04d}.geojson"] = generate_geojson(200).encode(
            "utf-8",
        )

    for i, size_kb in enumerate(num_binaries):
        entries[f"rasters/raster_{i:04d}.tiff"] = generate_binary_blob(size_kb)
        entries[f"vectors/vector_{i:04d}.gpkg"] = generate_binary_blob(size_kb)

    return entries


def write_test_data_to_disk(target_dir: str, entries: dict[str, bytes]) -> None:
    """Write entries dict to a directory tree on disk."""
    for arcname, content in entries.items():
        full_path = os.path.join(target_dir, arcname)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)


def load_real_data_entries(
    base_dir: str | None = None,
) -> dict[str, bytes]:
    """Walk real_data/ directory and load all files as entries.

    Args:
        base_dir: Path to search.  Defaults to <this_file>/../real_data/.

    Returns:
        Dict mapping relative arcnames (using / separator) to content bytes.
        Returns empty dict if real_data/ does not exist or is empty.

    """
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(__file__), "real_data")
    if not os.path.isdir(base_dir):
        return {}

    entries: dict[str, bytes] = {}
    for dirpath, _dirnames, filenames in os.walk(base_dir):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, base_dir).replace(os.sep, "/")
            try:
                with open(full, "rb") as f:
                    entries[rel] = f.read()
            except (OSError, PermissionError):
                continue  # skip unreadable files
    return entries


def real_data_available(base_dir: str | None = None) -> bool:
    """Return True if real_data/ exists and has files."""
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(__file__), "real_data")
    return os.path.isdir(base_dir) and bool(os.listdir(base_dir))


def get_real_data_dir() -> str:
    """Return the absolute path to tests/real_data/."""
    return os.path.join(os.path.dirname(__file__), "real_data")


def get_scenario_registry() -> dict[str, dict[str, bytes]]:
    """Return a dict of named scenarios for benchmarks."""
    return {
        "tiny": {
            "project.qgs": generate_qgs_project(num_layers=1, shared_symbols=1).encode(
                "utf-8",
            ),
            "data.geojson": generate_geojson(5).encode("utf-8"),
        },
        "small": {
            "project.qgs": generate_qgs_project(num_layers=3, shared_symbols=2).encode(
                "utf-8",
            ),
            "styles/style.qml": generate_qml_style(2).encode("utf-8"),
            "data.geojson": generate_geojson(20).encode("utf-8"),
            "data.csv": generate_csv(30).encode("utf-8"),
        },
        "standard": make_standard_test_set(),
        "text_heavy": {
            f"text_{i:04d}.qgs": generate_qgs_project(
                num_layers=8,
                shared_symbols=6,
            ).encode("utf-8")
            for i in range(20)
        },
        "binary_heavy": {
            f"binary_{i:04d}.tiff": generate_binary_blob(1024) for i in range(10)
        },
        "mixed": dict(
            **{
                f"project_{i:04d}.qgs": generate_qgs_project(
                    num_layers=5,
                    shared_symbols=4,
                ).encode("utf-8")
                for i in range(10)
            },
            **{f"raster_{i:04d}.tiff": generate_binary_blob(256) for i in range(10)},
        ),
    }
