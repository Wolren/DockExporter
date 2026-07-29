"""Tests for format detection — vector/raster driver lists and helpers.

All tests here exercise the format registry in ``dock_export.export._formats``,
which falls back to static lists when GDAL is unavailable, so these tests
work without a QGIS or GDAL installation.
"""

from __future__ import annotations

from dock_export.export._formats import (
    AVAILABLE_RASTER_DRIVERS,
    AVAILABLE_VECTOR_DRIVERS,
    DRIVER_LABELS,
    get_raster_formats,
    get_vector_formats,
)


class TestDriverLabels:
    """Every driver in the ordered lists must have a display label."""

    def test_all_vectors_have_labels(self):
        missing = [d for d in AVAILABLE_VECTOR_DRIVERS if d not in DRIVER_LABELS]
        assert not missing, f"Vector drivers missing labels: {missing}"

    def test_all_rasters_have_labels(self):
        missing = [d for d in AVAILABLE_RASTER_DRIVERS if d not in DRIVER_LABELS]
        assert not missing, f"Raster drivers missing labels: {missing}"


class TestAvailableDrivers:
    """AVAILABLE_VECTOR_DRIVERS and AVAILABLE_RASTER_DRIVERS are non-empty."""

    def test_vector_drivers_nonempty(self):
        assert len(AVAILABLE_VECTOR_DRIVERS) > 0
        assert isinstance(AVAILABLE_VECTOR_DRIVERS, frozenset)

    def test_raster_drivers_nonempty(self):
        assert len(AVAILABLE_RASTER_DRIVERS) > 0
        assert isinstance(AVAILABLE_RASTER_DRIVERS, frozenset)

    def test_vector_contains_gpkg(self):
        assert "GPKG" in AVAILABLE_VECTOR_DRIVERS

    def test_raster_contains_gtiff(self):
        assert "GTiff" in AVAILABLE_RASTER_DRIVERS


class TestVectorRasterOverlap:
    """Drivers that appear in both lists (MBTiles, PDF) are known exceptions."""

    _SHARED_DRIVERS = {"MBTiles", "PDF"}

    def test_known_shared_drivers_are_in_both(self):
        for d in self._SHARED_DRIVERS:
            assert d in AVAILABLE_VECTOR_DRIVERS, f"{d} should be in vector list"
            assert d in AVAILABLE_RASTER_DRIVERS, f"{d} should be in raster list"

    def test_no_unexpected_overlap(self):
        overlap = AVAILABLE_VECTOR_DRIVERS & AVAILABLE_RASTER_DRIVERS
        unexpected = overlap - self._SHARED_DRIVERS
        assert (
            not unexpected
        ), f"Unexpected vector/raster overlap: {unexpected}"


class TestGetVectorFormats:
    def test_returns_list_of_tuples(self):
        result = get_vector_formats()
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)  # label
            assert isinstance(item[1], str)  # driver name

    def test_include_default_adds_entry(self):
        without = get_vector_formats(include_default=False)
        with_default = get_vector_formats(include_default=True)
        assert len(with_default) == len(without) + 1
        assert with_default[0] == ("Default", "")

    def test_gpkg_is_present(self):
        labels = [label for label, driver in get_vector_formats()]
        assert any("GeoPackage" in label for label in labels)

    def test_excluded_db_drivers_not_present(self):
        drivers = {driver for _label, driver in get_vector_formats()}
        for banned in ("PostgreSQL", "MySQL", "MSSQLSpatial", "Oracle", "SDE"):
            assert banned not in drivers, f"{banned} should be excluded"


class TestGetRasterFormats:
    def test_returns_list_of_tuples(self):
        result = get_raster_formats()
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], str)

    def test_include_default_adds_entry(self):
        without = get_raster_formats(include_default=False)
        with_default = get_raster_formats(include_default=True)
        assert len(with_default) == len(without) + 1

    def test_gtiff_is_present(self):
        labels = [label for label, driver in get_raster_formats()]
        assert any("GeoTIFF" in label for label in labels)


class TestDriverLabelConsistency:
    """DRIVER_LABELS dict contains no duplicates and all values are non-empty."""

    def test_no_duplicate_labels(self):
        labels = list(DRIVER_LABELS.values())
        assert len(labels) == len(set(labels))

    def test_all_values_nonempty(self):
        empty = [k for k, v in DRIVER_LABELS.items() if not v]
        assert not empty, f"Empty labels for drivers: {empty}"
