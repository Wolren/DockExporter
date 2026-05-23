"""pytest fixtures for .woof compressor tests."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Generator

import pytest
from test_data_gen import (
    get_real_data_dir,
    load_real_data_entries,
    make_standard_test_set,
    real_data_available,
)


@pytest.fixture(scope="function")
def test_entries() -> dict[str, bytes]:
    """Standard test data for roundtrip tests."""
    return make_standard_test_set()


@pytest.fixture(scope="function")
def temp_dir() -> Generator[str, None, None]:
    """Temporary directory for extract tests, cleaned up after."""
    d = tempfile.mkdtemp(prefix="woof_test_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="function")
def temp_file(tmp_path) -> str:
    """Return a temp file path."""
    return str(tmp_path / "test.woof")


@pytest.fixture(scope="session")
def real_data_path() -> str:
    """Return path to tests/real_data/ (may not exist)."""
    return get_real_data_dir()


@pytest.fixture(scope="session")
def real_data_entries() -> dict[str, bytes]:
    """Load real data from tests/real_data/ for integration tests.

    Files larger than 100 MB are excluded to keep memory manageable.
    Returns empty dict when real_data/ does not exist or is empty,
    allowing dependent tests to skip gracefully.
    """
    if not real_data_available():
        return {}
    entries = load_real_data_entries()
    # Exclude huge files (>20 MB) to keep test memory manageable
    max_bytes = 20 * 1024 * 1024
    filtered = {k: v for k, v in entries.items() if len(v) <= max_bytes}
    dropped = len(entries) - len(filtered)
    if dropped:
        dropped_mb = (
            sum(len(v) for v in entries.values() if len(v) > max_bytes) / 1_048_576
        )
        print(
            f"  [real_data] Excluded {dropped} files ({dropped_mb:.1f} MB) exceeding 100 MB limit",
        )
    return filtered
