"""pytest fixtures for DockExporter tests.
Stubs qgis modules so tests can run without QGIS installed.
"""
from __future__ import annotations

# Must be first -- stubs qgis before any test imports trigger real qgis
import os
import sys

_stubs_path = os.path.join(os.path.dirname(__file__), "qgis_stubs.py")
exec(compile(open(_stubs_path).read(), _stubs_path, "exec"))

import tempfile
import shutil
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
    return make_standard_test_set()


@pytest.fixture(scope="function")
def temp_dir() -> Generator[str, None, None]:
    d = tempfile.mkdtemp(prefix="woof_test_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="function")
def temp_file(tmp_path) -> str:
    return str(tmp_path / "test.woof")


@pytest.fixture(scope="session")
def real_data_path() -> str:
    return get_real_data_dir()


@pytest.fixture(scope="session")
def real_data_entries() -> dict[str, bytes]:
    if not real_data_available():
        return {}
    entries = load_real_data_entries()
    max_bytes = 20 * 1024 * 1024
    filtered = {k: v for k, v in entries.items() if len(v) <= max_bytes}
    return filtered
