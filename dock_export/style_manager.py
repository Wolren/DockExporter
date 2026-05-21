"""Style save/embed helpers for QML sidecar files, SLD files, and GPKG layer_styles table."""

import logging
import os

from qgis.core import QgsMapLayer, QgsVectorLayer

from .models import StyleMode

logger = logging.getLogger("DockExport.StyleManager")


class StyleManager:
    @staticmethod
    def save_qml(layer: QgsMapLayer, base_path: str) -> bool:
        """Save <base_path>.qml."""
        path = base_path if base_path.endswith(".qml") else base_path + ".qml"
        try:
            result = layer.saveNamedStyle(path)
            if isinstance(result, tuple):
                err = result[0]
            else:
                err = "" if result else "saveNamedStyle returned False"
            if err:
                logger.warning("Could not save QML for %s: %s", layer.name(), err)
                return False
            return True
        except Exception as exc:
            logger.error("save_qml error: %s", exc)
            return False

    @staticmethod
    def save_sld(layer: QgsMapLayer, base_path: str) -> bool:
        """Save <base_path>.sld (vector only)."""
        if not isinstance(layer, QgsVectorLayer):
            return False
        path = base_path if base_path.endswith(".sld") else base_path + ".sld"
        try:
            result = layer.saveSldStyle(path)
            if isinstance(result, tuple):
                err = result[0]
            else:
                err = "" if result else "saveSldStyle returned False"
            if err:
                logger.warning("Could not save SLD for %s: %s", layer.name(), err)
                return False
            return True
        except Exception as exc:
            logger.error("save_sld error: %s", exc)
            return False

    @staticmethod
    def embed_style_in_gpkg(
        layer: QgsMapLayer, gpkg_path: str, table_name: str
    ) -> bool:
        """Write current renderer+labeling into GPKG layer_styles table."""
        if not isinstance(layer, QgsVectorLayer):
            return False
        try:
            uri = f"{gpkg_path}|layername={table_name}"
            tmp = QgsVectorLayer(uri, table_name, "ogr")
            if not tmp.isValid():
                logger.warning("Could not open %s|layername=%s", gpkg_path, table_name)
                return False

            if layer.renderer():
                tmp.setRenderer(layer.renderer().clone())
            if layer.labeling():
                tmp.setLabeling(layer.labeling().clone())

            err = tmp.saveStyleToDatabase(table_name, "", True, "")
            if err:
                logger.warning("saveStyleToDatabase error for %s: %s", table_name, err)
                return False
            return True
        except Exception as exc:
            logger.error("embed_style_in_gpkg error: %s", exc)
            return False

    def apply_style_mode(
        self,
        source_layer: QgsMapLayer,
        style_mode: str,
        output_file_path: str,
        gpkg_table_name: str = "",
    ) -> None:
        """Dispatch to QML/SLD/embed based on style_mode."""
        if style_mode == StyleMode.NONE:
            return

        base = os.path.splitext(output_file_path)[0]

        if style_mode in (StyleMode.QML, StyleMode.BOTH):
            self.save_qml(source_layer, base)

        if style_mode in (StyleMode.SLD, StyleMode.BOTH):
            self.save_sld(source_layer, base)

        if style_mode == StyleMode.EMBED:
            self.embed_style_in_gpkg(source_layer, output_file_path, gpkg_table_name)
