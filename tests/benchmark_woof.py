#!/usr/bin/env python3
"""Comprehensive benchmark suite for .woof compressor with real-time rich display.

Measures every aspect of archiving performance across all modes (v1/v2/v3)
and scenarios (tiny / small / standard / text-heavy / binary-heavy / mixed).

Usage:
    python tests/benchmark_woof.py                           # run all
    python tests/benchmark_woof.py --scenario standard        # single scenario
    python tests/benchmark_woof.py --mode v2                  # single mode
    python tests/benchmark_woof.py --iterations 5             # more iterations
    python tests/benchmark_woof.py --output report.md         # save report
    python tests/benchmark_woof.py --quick                    # tiny only, 1 iter
    python tests/benchmark_woof.py --no-live                  # plain text (non-rich)
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import tracemalloc
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dock_export.woof_format import (
    HEADER_SIZE,
    WOOF_MAGIC,
    FLAG_XOR,
    FLAG_HAS_CHUNK_STORE,
    FLAG_ENTRY_CHUNKED,
    _xor,
    pack_woof,
    unpack_woof,
)
from tests.test_data_gen import (
    get_scenario_registry,
    make_standard_test_set,
    make_colossal_test_set,
    load_real_data_entries,
    real_data_available,
)

# Optional rich
_HAVE_RICH = False
try:
    from rich.console import Console
    from rich.live import Live
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.table import Table
    from rich.text import Text
    from rich.panel import Panel
    from rich.layout import Layout

    _HAVE_RICH = True
    _CONSOLE = Console()
except ImportError:
    _CONSOLE = None


# ── Type aliases ─────────────────────────────────────────────────

Metrics = Dict[str, float | int | str]

# ── Formatting helpers ───────────────────────────────────────────

_HUMAN_SUFFIXES = ["B", "KB", "MB", "GB"]


def _human_bytes(n: int) -> str:
    if n == 0:
        return "0 B"
    i = min(int(math.log(n, 1024)), len(_HUMAN_SUFFIXES) - 1)
    val = n / (1024**i)
    return f"{val:.2f} {_HUMAN_SUFFIXES[i]}"


def _human_time(sec: float) -> str:
    if sec < 0.001:
        return f"{sec * 1_000_000:.0f} us"
    if sec < 1:
        return f"{sec * 1_000:.2f} ms"
    return f"{sec:.3f} s"


def _human_ratio(ratio: float) -> str:
    return f"{ratio:.3f}x"


def _bar(val: float, max_val: float, width: int = 20) -> str:
    filled = int((val / max_val) * width) if max_val > 0 else 0
    filled = min(filled, width)
    return "#" * filled + "-" * (width - filled)


# ── Mode definitions ─────────────────────────────────────────────

_MODE_LABELS = {
    ("v1", False, False): "v1 (zlib, no compress)",
    ("v1", True, False): "v1 (zlib, compress)",
    ("v2", False, False): "v2 (zstd+CDC, no compress)",
    ("v2", True, False): "v2 (zstd+CDC, compress)",
    ("v3", True, True): "v3 (zstd+CDC+graph, compress)",
    ("v3", False, True): "v3 (zstd+CDC+graph, no compress)",
}


def _mode_key(mode: str, compress: bool, graph: bool):
    return (mode, compress, graph)


def _modes_to_benchmark(quick: bool = False) -> List[Tuple[str, bool, bool]]:
    modes = [
        ("v1", False, False),
        ("v1", True, False),
        ("v2", False, False),
        ("v2", True, False),
    ]
    try:
        import zstandard  # noqa: F401

        modes += [
            ("v3", True, True),
            ("v3", False, True),
        ]
    except ImportError:
        pass
    if quick:
        modes = [m for m in modes if m[1]]
    return modes


# ── Entry comparison (handles XML cosmetic differences for v3) ──

_XML_EXTS = {".qgs", ".qml", ".xml", ".sld", ".geojson", ".svg", ".txt"}


def _xml_infoset_equal(a: bytes, b: bytes) -> bool:
    """Compare two XML docs for infoset equality, ignoring formatting."""
    if a == b:
        return True
    try:
        import xml.etree.ElementTree as ET

        root_a = ET.fromstring(a)
        root_b = ET.fromstring(b)
    except Exception:
        return False

    def _compare(e1: ET.Element, e2: ET.Element) -> bool:
        if e1.tag != e2.tag:
            return False
        if e1.attrib != e2.attrib:
            return False
        t1 = (e1.text or "").strip()
        t2 = (e2.text or "").strip()
        if t1 != t2:
            return False
        c1 = list(e1)
        c2 = list(e2)
        if len(c1) != len(c2):
            return False
        return all(_compare(x, y) for x, y in zip(c1, c2))

    return _compare(root_a, root_b)


def _assert_entries_equal(
    result: Dict[str, bytes],
    expected: Dict[str, bytes],
    mode: str,
    compress: bool,
    graph: bool,
) -> None:
    """Compare entry dicts, handling cosmetic XML differences for v3."""
    if set(result.keys()) != set(expected.keys()):
        missing = set(expected.keys()) - set(result.keys())
        extra = set(result.keys()) - set(expected.keys())
        msg = f"Key mismatch in {mode} c={compress} g={graph}"
        if missing:
            msg += f" missing={missing}"
        if extra:
            msg += f" extra={extra}"
        raise AssertionError(msg)
    for key in expected:
        a, b = expected[key], result[key]
        if graph and any(key.lower().endswith(ext) for ext in _XML_EXTS):
            if not _xml_infoset_equal(a, b):
                raise AssertionError(
                    f"XML content mismatch for {key!r} in {mode} c={compress} g={graph}"
                )
        elif a != b:
            size_diff = len(a) != len(b)
            raise AssertionError(
                f"Content mismatch for {key!r} in {mode} c={compress} "
                f"g={graph} size_diff={size_diff}"
            )


# ── Core benchmark ───────────────────────────────────────────────


def _bench_one(
    entries: Dict[str, bytes],
    mode: str,
    compress: bool,
    graph: bool,
    iterations: int = 3,
    warmup: int = 1,
) -> Metrics:
    meta: Metrics = {
        "mode": mode,
        "compress": compress,
        "graph_dedup": graph,
        "entries": len(entries),
        "raw_size": sum(len(c) for c in entries.values()),
    }

    kwargs = {"compress": compress, "graph_dedup": graph}
    if mode == "v1":
        kwargs["use_v2"] = False
    elif mode in ("v2", "v3"):
        kwargs["use_v2"] = True

    for _ in range(warmup):
        _ = pack_woof(entries, **kwargs)

    pack_times: List[float] = []
    pack_sizes: List[int] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        packed = pack_woof(entries, **kwargs)
        t1 = time.perf_counter()
        pack_times.append(t1 - t0)
        pack_sizes.append(len(packed))

    tracemalloc.start()
    _ = pack_woof(entries, **kwargs)
    _current, peak_pack = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    meta["pack_time"] = sum(pack_times) / len(pack_times)
    meta["archive_size"] = sum(pack_sizes) // len(pack_sizes)
    raw = meta["raw_size"]
    arch = meta["archive_size"]
    meta["ratio"] = round(raw / arch, 3) if arch > 0 else 0.0
    meta["overhead_bytes"] = arch - HEADER_SIZE
    meta["overhead_pct"] = (
        round((arch - HEADER_SIZE) / arch * 100, 2) if arch > 0 else 0
    )
    meta["pack_speed_mbps"] = (
        round((raw / 1_048_576) / meta["pack_time"], 3)
        if meta["pack_time"] > 0
        else 0.0
    )
    meta["pack_memory_kb"] = peak_pack // 1024

    for _ in range(warmup):
        _ = unpack_woof(packed)

    unpack_times: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = unpack_woof(packed)
        t1 = time.perf_counter()
        if graph:
            _assert_entries_equal(result, entries, mode, compress, graph)
        else:
            assert result == entries, (
                f"Roundtrip failed in {mode} compress={compress} graph={graph}"
            )
        unpack_times.append(t1 - t0)

    tracemalloc.start()
    _ = unpack_woof(packed)
    _current, peak_unpack = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    meta["unpack_time"] = sum(unpack_times) / len(unpack_times)
    meta["unpack_speed_mbps"] = (
        round((raw / 1_048_576) / meta["unpack_time"], 3)
        if meta["unpack_time"] > 0
        else 0.0
    )
    meta["unpack_memory_kb"] = peak_unpack // 1024

    # Parse payload for chunk/resource stats
    try:
        import struct as _struct

        _magic, _ver, hdr_flags, xor_size, _raw_total = _struct.unpack(
            "<4sIQQQ", packed[:HEADER_SIZE]
        )
        payload = packed[HEADER_SIZE : HEADER_SIZE + xor_size]
        if hdr_flags & FLAG_XOR:
            payload = _xor(payload)

        pos = 0
        if hdr_flags & FLAG_HAS_CHUNK_STORE:
            (num_chunks,) = _struct.unpack_from("<Q", payload, pos)
            meta["num_chunks"] = num_chunks
            pos += 8
            unique_sizes = []
            for _ in range(num_chunks):
                pos += 32
                comp_size, rsize = _struct.unpack_from("<QQ", payload, pos)
                pos += 16
                unique_sizes.append(rsize)
                pos += comp_size
            meta["unique_chunks"] = num_chunks
            meta["dedup_total_raw"] = sum(unique_sizes)
            meta["avg_chunk_size"] = (
                round(sum(unique_sizes) / num_chunks, 1) if num_chunks > 0 else 0
            )
        else:
            meta["num_chunks"] = 0
            meta["unique_chunks"] = 0
            meta["dedup_total_raw"] = 0
            meta["avg_chunk_size"] = 0

        ftable = payload[pos:]
        num_entries = 0
        fp = 0
        while fp < len(ftable):
            num_entries += 1
            _flags, name_len = _struct.unpack_from("<II", ftable, fp)
            fp += 8 + name_len
            if _flags & FLAG_ENTRY_CHUNKED:
                num_hashes, _tt = _struct.unpack_from("<II", ftable, fp)
                fp += 8 + num_hashes * 32
            else:
                (data_len,) = _struct.unpack_from("<Q", ftable, fp)
                fp += 8 + data_len
        meta["file_entries"] = num_entries

    except Exception as exc:
        meta["parse_error"] = str(exc)

    return meta


# ── Rich-based live display ──────────────────────────────────────


def _build_live_table(
    completed: List[Tuple[str, str, Metrics]],
    pending_count: int,
    current_label: str,
    elapsed: float,
) -> Table:
    """Build a rich Table showing completed benchmarks + current running."""
    table = Table(
        title=f"Benchmark in progress ({elapsed:.0f}s elapsed, ~{pending_count} remaining)",
        box=None,
        title_justify="left",
        padding=(0, 1),
    )
    table.add_column("Mode", style="cyan", no_wrap=True)
    table.add_column("Archive", style="yellow", no_wrap=True)
    table.add_column("Ratio", style="green", justify="right")
    table.add_column("Pack", justify="right")
    table.add_column("Unpack", justify="right")
    table.add_column("Speed", style="magenta", justify="right")
    table.add_column("Mem(P)", justify="right")
    table.add_column("Mem(U)", justify="right")
    table.add_column("Chunks", justify="right")

    for scenario, mode_label, m in completed:
        if m.get("error"):
            table.add_row(mode_label, "[red]FAILED[/red]", "", "", "", "", "", "", "")
        else:
            table.add_row(
                mode_label,
                _human_bytes(m["archive_size"]),
                f"{m['ratio']:.2f}x",
                _human_time(m["pack_time"]),
                _human_time(m["unpack_time"]),
                f"{m['pack_speed_mbps']:.1f}/{m['unpack_speed_mbps']:.1f} MB/s",
                _human_bytes(m["pack_memory_kb"] * 1024),
                _human_bytes(m["unpack_memory_kb"] * 1024),
                str(m.get("num_chunks", "?")),
            )

    if current_label:
        table.add_row(
            current_label,
            "[dim]... running[/dim]",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        )

    return table


def _build_bar_chart(
    metrics_list: List[Metrics], title: str = "Compression Ratio"
) -> Panel:
    """Build a bar chart panel from completed metrics."""
    if not metrics_list:
        return Panel("No data yet", title=title)

    max_ratio = max(float(m["ratio"]) for m in metrics_list)
    lines: List[str] = []
    for m in sorted(metrics_list, key=lambda x: float(x["ratio"]), reverse=True):
        label = _MODE_LABELS.get(
            _mode_key(m["mode"], m["compress"], m["graph_dedup"]),
            f"{m['mode']} c={m['compress']} g={m['graph_dedup']}",
        )
        bar = _bar(float(m["ratio"]), max_ratio, width=30)
        lines.append(f"  {label:<26} {bar} {m['ratio']:.2f}x")

    return Panel("\n".join(lines), title=title, padding=(0, 1))


def _build_summary_layout(
    scenario: str,
    raw_info: str,
    scenario_metrics: List[Metrics],
    all_metrics: Dict[str, List[Metrics]],
    status_text: str = "",
) -> Layout:
    """Build a rich Layout with scenario info, bar chart, and cross-scenario summary."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
    )

    # Header
    total_tests = sum(len(v) for v in all_metrics.values()) if all_metrics else 0
    scenario_count = len(all_metrics)
    header_text = Text.assemble(
        ("Scenario: ", "bold white"),
        (scenario, "bold cyan"),
        (" \u2014 ", "dim"),
        (raw_info, "yellow"),
        (" | Completed: ", "dim"),
        (str(scenario_count), "green"),
        (" scenarios, ", "dim"),
        (str(total_tests), "green"),
        (" tests", "dim"),
    )
    if status_text:
        header_text.append(f" | {status_text}", style="cyan")
    layout["header"].update(Panel(header_text, padding=(0, 1)))

    # Main split: bar chart + cross summary
    main_layout = Layout()
    main_layout.split_row(
        Layout(name="chart", ratio=2),
        Layout(name="cross", ratio=1),
    )

    # Bar chart
    chart_panel = _build_bar_chart(
        scenario_metrics, f"Compression Ratio \u2014 {scenario}"
    )
    main_layout["chart"].update(chart_panel)

    # Cross-scenario summary
    cross_lines = ["[bold]Cross-Scenario Ratios[/bold]"]
    fmt = "{:<16}  " + " ".join("{:>10}" for _ in range(len(scenario_metrics)))
    if scenario_metrics:
        headers = " ".join(
            f"{_MODE_LABELS.get(_mode_key(m['mode'], m['compress'], m['graph_dedup']), m['mode']):>10}"
            for m in scenario_metrics
        )
        cross_lines.append(f"  {'Scenario':<16}  {headers}")
        cross_lines.append("  " + "-" * (16 + 2 + 11 * len(scenario_metrics)))
        for sc_name, sc_metrics in all_metrics.items():
            ratios = " ".join(f"{m['ratio']:>10.3f}" for m in sc_metrics)
            cross_lines.append(f"  {sc_name:<16}  {ratios}")

    main_layout["cross"].update(Panel("\n".join(cross_lines), title="Cross-Scenario"))

    return layout


# ── Plain text fallback ──────────────────────────────────────────


def _plain_print_progress(
    scenario: str,
    label: str,
    mode_idx: int,
    total_modes: int,
) -> None:
    sys.stdout.write(f"  [{scenario}] {label:<30} ... ")
    sys.stdout.flush()


def _plain_print_result(m: Metrics, failed: bool = False) -> None:
    if failed:
        print(f"FAILED: {m.get('error', 'unknown')}")
        return
    ratio = m.get("ratio", 0)
    pack_t = _human_time(m["pack_time"])
    unpack_t = _human_time(m["unpack_time"])
    arch = _human_bytes(m["archive_size"])
    mem = _human_bytes(m["pack_memory_kb"] * 1024)
    num_c = m.get("num_chunks", "?")
    print(
        f"OK {arch}  ratio={ratio:.2f}x  {pack_t}/{unpack_t}  mem={mem}  chunks={num_c}"
    )


# ── Report generation ────────────────────────────────────────────

_HEADER_SEP = "=" * 100


def _build_report(
    all_metrics: Dict[str, List[Metrics]],
    scenario_order: List[str],
) -> str:
    lines: List[str] = []
    lines.append("# .woof Compressor Benchmark Report")
    lines.append(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\nPython: {sys.version}")
    try:
        import zstandard

        lines.append(f"zstandard: {zstandard.__version__}")
    except ImportError:
        lines.append("zstandard: NOT AVAILABLE")
    lines.append(f"\nTotal scenarios: {len(scenario_order)}")
    lines.append(
        f"Total benchmark configurations: {sum(len(v) for v in all_metrics.values())}"
    )

    for scenario in scenario_order:
        metrics_list = all_metrics.get(scenario, [])
        if not metrics_list:
            continue

        lines.append(f"\n{_HEADER_SEP}")
        lines.append(f"## Scenario: {scenario}")
        lines.append(
            f"\nEntries: {metrics_list[0]['entries']}, "
            f"Raw size: {_human_bytes(metrics_list[0]['raw_size'])}"
        )

        cols = [
            ("Mode", 24),
            ("Arch Size", 12),
            ("Ratio", 8),
            ("Pack", 12),
            ("Unpack", 12),
            ("Speed(P/U)", 22),
            ("Mem(P)", 10),
            ("Mem(U)", 10),
            ("Chunks", 8),
        ]
        headers = [c[0] for c in cols]
        widths = [c[1] for c in cols]

        def _fmt_row(entries: List[str], w: List[int]) -> str:
            parts = [f"{entries[0]:<{w[0]}}"]
            for i in range(1, len(entries)):
                parts.append(f"{entries[i]:>{w[i]}}")
            return " | ".join(parts)

        def _fmt_sep(w: List[int]) -> str:
            return "-+-".join("-" * w_i for w_i in w)

        lines.append(f"\n{_fmt_row(headers, widths)}")
        lines.append(_fmt_sep(widths))

        for m in metrics_list:
            label = _MODE_LABELS.get(
                _mode_key(m["mode"], m["compress"], m["graph_dedup"]),
                f"{m['mode']} c={m['compress']} g={m['graph_dedup']}",
            )
            row = [
                _human_bytes(m["archive_size"]),
                _human_ratio(m["ratio"]),
                _human_time(m["pack_time"]),
                _human_time(m["unpack_time"]),
                f"{m['pack_speed_mbps']:.1f} / {m['unpack_speed_mbps']:.1f} MB/s",
                _human_bytes(m["pack_memory_kb"] * 1024),
                _human_bytes(m["unpack_memory_kb"] * 1024),
                str(m.get("num_chunks", "?")),
            ]
            lines.append(_fmt_row([label] + row, widths))

        lines.append(f"\n**Ratio comparison (higher = better):**")
        max_ratio = max(m["ratio"] for m in metrics_list)
        for m in sorted(metrics_list, key=lambda x: x["ratio"], reverse=True):
            label = _MODE_LABELS.get(
                _mode_key(m["mode"], m["compress"], m["graph_dedup"]), f"{m['mode']}"
            )
            bar = _bar(float(m["ratio"]), max_ratio)
            lines.append(f"  {label:<24} {bar} {m['ratio']:.2f}x")

    # Cross-scenario summary
    lines.append(f"\n{_HEADER_SEP}")
    lines.append("## Cross-Scenario Summary (Compression Ratio)")
    first_scenario_metrics = all_metrics.get(scenario_order[0], [])
    if first_scenario_metrics:
        lines.append(
            f"\n{'Scenario':<20} "
            + " ".join(
                f"{_MODE_LABELS.get(_mode_key(m['mode'], m['compress'], m['graph_dedup']), m['mode']):>16}"
                for m in first_scenario_metrics
            )
        )
        lines.append("-" * 100)
        for scenario in scenario_order:
            metrics_list = all_metrics.get(scenario, [])
            if not metrics_list:
                continue
            ratios = " ".join(f"{m['ratio']:>16.3f}" for m in metrics_list)
            lines.append(f"{scenario:<20} {ratios}")

    # Recommendations
    lines.append(f"\n{_HEADER_SEP}")
    lines.append("## Recommendations")
    best_ratio = 0.0
    best_mode = ""
    best_speed = float("inf")
    best_speed_mode = ""
    best_mem = float("inf")
    best_mem_mode = ""
    for scenario in scenario_order:
        for m in all_metrics.get(scenario, []):
            if m["ratio"] > best_ratio:
                best_ratio = m["ratio"]
                best_mode = (
                    f"{m['mode']} compress={m['compress']} graph={m['graph_dedup']}"
                )
            if m["pack_time"] < best_speed and m["compress"]:
                best_speed = m["pack_time"]
                best_speed_mode = (
                    f"{m['mode']} compress={m['compress']} graph={m['graph_dedup']}"
                )
            if m["pack_memory_kb"] < best_mem:
                best_mem = m["pack_memory_kb"]
                best_mem_mode = (
                    f"{m['mode']} compress={m['compress']} graph={m['graph_dedup']}"
                )
    lines.append(f"- **Best compression ratio**: {best_ratio:.3f}x ({best_mode})")
    lines.append(f"- **Fastest pack**: {_human_time(best_speed)} ({best_speed_mode})")
    lines.append(
        f"- **Lowest memory**: {_human_bytes(best_mem * 1024)} ({best_mem_mode})"
    )

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=".woof compressor comprehensive benchmark suite",
    )
    parser.add_argument(
        "--scenario",
        choices=[
            "all",
            "tiny",
            "small",
            "standard",
            "text_heavy",
            "binary_heavy",
            "mixed",
        ],
        default="all",
        help="Which scenario to benchmark (default: all)",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "v1", "v2", "v3"],
        default="all",
        help="Which compression mode to test (default: all)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of timed iterations (default: 3)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Warmup iterations (default: 1)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write report to file (e.g. benchmark_report.md)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick mode: tiny scenario, 1 iteration, compress only",
    )
    parser.add_argument(
        "--colossal",
        action="store_true",
        help="Use 100MB+ colossal test set instead of standard",
    )
    parser.add_argument(
        "--real-data",
        action="store_true",
        help="Include real_data/ directory contents as a benchmark scenario",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        dest="no_live",
        help="Disable rich live display (plain text output)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Also generate HTML report alongside markdown (requires rich)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    use_live = _HAVE_RICH and not args.no_live

    if args.quick:
        args.scenario = "tiny"
        args.iterations = 1
        args.warmup = 0

    registry = get_scenario_registry()
    if args.colossal:
        registry["colossal"] = make_colossal_test_set(
            num_qgs=20, num_styles=30, num_geojson=50, num_binaries=[512, 1024, 4096]
        )
        if args.scenario == "all":
            args.scenario = "colossal"

    if args.real_data:
        if real_data_available():
            real_entries = load_real_data_entries()
            if real_entries:
                total_mb = sum(len(c) for c in real_entries.values()) / 1_048_576
                print(
                    f"  Loaded real data: {len(real_entries)} files, {total_mb:.1f} MB"
                )
                registry["real_data"] = real_entries
            else:
                print("  Warning: --real-data requested but real_data/ is empty")
        else:
            print("  Warning: --real-data requested but tests/real_data/ not found")

    if args.scenario == "all":
        scenario_order = ["tiny", "small", "standard"]
        for name in ["text_heavy", "binary_heavy", "mixed"]:
            if name in registry:
                scenario_order.append(name)
        if args.colossal:
            scenario_order.append("colossal")
        if args.real_data and "real_data" in registry:
            scenario_order.append("real_data")
    else:
        scenario_order = [args.scenario]

    scenario_order = [s for s in scenario_order if s in registry]
    if not scenario_order:
        print("No matching scenarios found.")
        sys.exit(1)

    all_modes = _modes_to_benchmark(args.quick)
    if args.mode == "v1":
        all_modes = [m for m in all_modes if m[0] == "v1"]
    elif args.mode == "v2":
        all_modes = [m for m in all_modes if m[0] == "v2"]
    elif args.mode == "v3":
        all_modes = [m for m in all_modes if m[0] == "v3"]

    if not all_modes:
        print("No matching modes found.")
        sys.exit(1)

    total_tests = len(scenario_order) * len(all_modes)
    console = _CONSOLE if use_live else None

    # ── Plain text run ───────────────────────────────────────────
    if not use_live:
        print(f"\n{'=' * 100}")
        print(f"  .WOOF COMPRESSOR BENCHMARK")
        print(f"  Scenarios: {', '.join(scenario_order)}")
        print(f"  Modes:     {', '.join(m[0] for m in all_modes)}")
        print(f"  Iterations per test: {args.iterations}")
        print(f"  Total tests: {total_tests}")
        print(f"{'=' * 100}\n")

        all_metrics: Dict[str, List[Metrics]] = {}
        for scenario in scenario_order:
            entries = registry[scenario]
            raw_mb = sum(len(c) for c in entries.values()) / 1_048_576
            print(
                f"\n==> Scenario: [{scenario}] -- {len(entries)} files, {raw_mb:.1f} MB raw"
            )

            scenario_metrics: List[Metrics] = []
            for mode, compress, graph in all_modes:
                label = _MODE_LABELS.get(
                    _mode_key(mode, compress, graph), f"{mode} c={compress} g={graph}"
                )
                _plain_print_progress(scenario, label, 0, 0)
                try:
                    m = _bench_one(
                        entries,
                        mode=mode,
                        compress=compress,
                        graph=graph,
                        iterations=args.iterations,
                        warmup=args.warmup,
                    )
                    scenario_metrics.append(m)
                    _plain_print_result(m)
                except Exception as e:
                    scenario_metrics.append(
                        {
                            "error": str(e),
                            "mode": mode,
                            "compress": compress,
                            "graph_dedup": graph,
                            "ratio": 0,
                            "archive_size": 0,
                            "pack_time": 0,
                            "unpack_time": 0,
                            "pack_speed_mbps": 0,
                            "unpack_speed_mbps": 0,
                            "pack_memory_kb": 0,
                            "unpack_memory_kb": 0,
                            "num_chunks": 0,
                        }
                    )
                    _plain_print_result({"error": str(e)}, failed=True)

            all_metrics[scenario] = scenario_metrics

        report = _build_report(all_metrics, scenario_order)
        print(f"\n{_HEADER_SEP}")
        print(report)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\nReport saved to: {args.output}")
        return

    # ── Rich live run ────────────────────────────────────────────
    # Build progress bars
    overall_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        console=console,
    )
    scenario_progress = Progress(
        TextColumn("  {task.description}"),
        BarColumn(bar_width=30),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=console,
    )

    progress_table = Table.grid(padding=(0, 1))
    progress_table.add_row(
        Panel(overall_progress, title="Overall Progress", padding=(0, 1)),
    )
    progress_table.add_row(
        Panel(scenario_progress, title="Current Scenario", padding=(0, 1)),
    )

    layout = Layout()
    layout.split_column(
        Layout(name="progress", size=6),
        Layout(name="summary", ratio=1),
        Layout(name="info", size=3),
    )
    layout["progress"].update(progress_table)

    all_metrics = {}
    completed_list: List[Tuple[str, str, Metrics]] = []
    start_time = time.time()

    # Calc total work
    total_jobs = len(scenario_order) * len(all_modes)
    overall_task = overall_progress.add_task("[cyan]Benchmarking...", total=total_jobs)

    with Live(layout, console=console, refresh_per_second=4, screen=True):
        for scenario in scenario_order:
            entries = registry[scenario]
            raw_mb = sum(len(c) for c in entries.values()) / 1_048_576
            raw_info = f"{len(entries)} files, {raw_mb:.1f} MB raw"

            scenario_metrics = []
            sc_task = scenario_progress.add_task(
                f"[yellow]{scenario}", total=len(all_modes)
            )

            for mode, compress, graph in all_modes:
                label = _MODE_LABELS.get(
                    _mode_key(mode, compress, graph),
                    f"{mode} c={compress} g={graph}",
                )
                mode_label = f"[cyan]{mode}[/cyan] {'c' if compress else 'nc'} {'g' if graph else 'ng'}"

                # Update info panel
                elapsed = time.time() - start_time
                remaining = total_jobs - (len(completed_list) + 1)
                eta = (
                    (elapsed / (len(completed_list) + 1)) * remaining
                    if completed_list
                    else 0
                )
                info_text = Text.assemble(
                    ("Current: ", "bold"),
                    (f"[{scenario}] ", "yellow"),
                    (label, "cyan"),
                    (" | Elapsed: ", "dim"),
                    (_human_time(elapsed), "green"),
                    (" | ETA: ", "dim"),
                    (_human_time(eta) if remaining > 0 else "done", "green"),
                    (" | Completed: ", "dim"),
                    (f"{len(completed_list)}/{total_jobs}", "green"),
                )
                layout["info"].update(Panel(info_text, padding=(0, 1)))

                # Update summary layout
                summary_layout = _build_summary_layout(
                    scenario,
                    raw_info,
                    scenario_metrics,
                    all_metrics,
                    status_text=f"running {label}...",
                )
                layout["summary"].update(summary_layout)

                try:
                    m = _bench_one(
                        entries,
                        mode=mode,
                        compress=compress,
                        graph=graph,
                        iterations=args.iterations,
                        warmup=args.warmup,
                    )
                    scenario_metrics.append(m)
                    completed_list.append((scenario, mode_label, m))
                except Exception as e:
                    err_metrics: Metrics = {
                        "mode": mode,
                        "compress": compress,
                        "graph_dedup": graph,
                        "error": str(e),
                        "ratio": 0,
                        "archive_size": 0,
                        "pack_time": 0,
                        "unpack_time": 0,
                        "pack_speed_mbps": 0,
                        "unpack_speed_mbps": 0,
                        "pack_memory_kb": 0,
                        "unpack_memory_kb": 0,
                        "num_chunks": 0,
                        "entries": 0,
                        "raw_size": 0,
                    }
                    scenario_metrics.append(err_metrics)
                    completed_list.append(
                        (scenario, f"[red]{mode_label} FAILED[/red]", err_metrics)
                    )

                scenario_progress.update(sc_task, advance=1)
                overall_progress.update(overall_task, advance=1)

            all_metrics[scenario] = scenario_metrics

        # Final update: done
        elapsed = time.time() - start_time
        info_text = Text.assemble(
            ("All benchmarks complete! ", "bold green"),
            (f"Total time: {_human_time(elapsed)}", "green"),
            (
                f" | {len(completed_list)} tests across {len(scenario_order)} scenarios",
                "dim",
            ),
        )
        layout["info"].update(Panel(info_text, padding=(0, 1)))

        final_summary = _build_summary_layout(
            scenario_order[-1],
            f"{sum(len(registry[s]) for s in scenario_order)} files total",
            all_metrics.get(scenario_order[-1], []),
            all_metrics,
            status_text="[bold green]COMPLETE[/bold green]",
        )
        layout["summary"].update(final_summary)

    # Generate report after live display ends
    report = _build_report(all_metrics, scenario_order)

    print(f"\n{'=' * 100}")
    print(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport saved to: {args.output}")

    if args.html and _HAVE_RICH:
        html_path = (
            args.output.replace(".md", ".html")
            if args.output
            else "benchmark_report.html"
        )
        from rich.console import Console as RichConsole

        html_console = RichConsole(record=True)
        html_console.print(report)
        html_console.save_html(html_path)
        print(f"HTML report saved to: {html_path}")


if __name__ == "__main__":
    main()
