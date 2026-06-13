"""Tests for utility functions extracted from project_export_tab.

These functions have no QGIS dependency and can be tested with plain Python.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dock_export.export._utils import _SIDECAR_EXTS, collect_sidecar_files


class TestSidecarExts:
    def test_known_extensions(self):
        for ext in (".qml", ".sld", ".tfw", ".pgw", ".jgw", ".gw", ".wld", ".aux.xml"):
            assert ext in _SIDECAR_EXTS

    def test_no_junk(self):
        assert ".py" not in _SIDECAR_EXTS
        assert ".xml" not in _SIDECAR_EXTS


class TestCollectSidecarFiles:
    def test_no_sidecars(self):
        assert collect_sidecar_files(["/tmp/test.shp"]) == []

    def test_with_qml_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "test")
            shp = base + ".shp"
            qml = base + ".qml"
            with open(shp, "w") as f:
                f.write("")
            with open(qml, "w") as f:
                f.write("")

            result = collect_sidecar_files([shp])
            assert qml in result
            assert shp not in result
            assert len(result) == 1

    def test_all_sidecar_exts(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "layer")
            src = base + ".shp"
            with open(src, "w") as f:
                f.write("")

            exts = [".qml", ".sld", ".tfw", ".pgw", ".jgw", ".gw", ".wld", ".aux.xml"]
            sidecars = []
            for ext in exts:
                path = base + ext
                with open(path, "w") as f:
                    f.write("")
                sidecars.append(path)

            result = collect_sidecar_files([src])
            assert len(result) == len(exts)
            for p in sidecars:
                assert p in result

    def test_no_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "test")
            shp1 = base + ".shp"
            shp2 = base + "_copy.shp"
            qml = base + ".qml"
            for p in (shp1, shp2, qml):
                with open(p, "w") as f:
                    f.write("")

            result = collect_sidecar_files([shp1, shp2])
            assert qml in result
            assert len(result) == 1

    def test_multiple_bases(self):
        with tempfile.TemporaryDirectory() as d:
            a_base = os.path.join(d, "a")
            b_base = os.path.join(d, "b")
            a_shp = a_base + ".shp"
            b_shp = b_base + ".shp"
            a_qml = a_base + ".qml"
            b_sld = b_base + ".sld"
            for p in (a_shp, b_shp, a_qml, b_sld):
                with open(p, "w") as f:
                    f.write("")

            result = collect_sidecar_files([a_shp, b_shp])
            assert a_qml in result
            assert b_sld in result
            assert len(result) == 2

    def test_missing_sidecar_ignored(self):
        result = collect_sidecar_files(["/nonexistent/file.shp"])
        assert result == []

    def test_empty_file_list(self):
        assert collect_sidecar_files([]) == []
