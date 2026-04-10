"""
style_manager.py  –  All style save / embed helpers.

Uses only PyQGIS APIs (no GeoPandas / external deps).
"""
import logging
import os

from qgis.core import QgsMapLayer, QgsVectorLayer, QgsRasterLayer

logger = logging.getLogger("DockExport.StyleManager")


class StyleManager:
    """Encapsulates QML / SLD save and GPKG embed logic."""

    # ------------------------------------------------------------------ #
    # Vector styles                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def save_qml(layer: QgsMapLayer, base_path: str) -> bool:
        """Save ``<base_path>.qml``."""
        path = base_path if base_path.endswith(".qml") else base_path + ".qml"
        try:
            # saveNamedStyle returns (error_msg, QML_content) in QGIS 3.x
            # and in QGIS 4.x it is the same signature via the compat layer.
            result = layer.saveNamedStyle(path)
            # result may be (error_string, bool) or just bool depending on version
            if isinstance(result, tuple):
                err = result[0]
            else:
                err = "" if result else "saveNamedStyle returned False"
            if err:
                logger.warning("Could not save QML for %s: %s", layer.name(), err)
                return False
            logger.info("QML saved: %s", path)
            return True
        except Exception as exc:
            logger.error("save_qml error: %s", exc)
            return False

    @staticmethod
    def save_sld(layer: QgsMapLayer, base_path: str) -> bool:
        """Save ``<base_path>.sld`` (vector only)."""
        if not isinstance(layer, QgsVectorLayer):
            logger.info("SLD export skipped for raster layer %s", layer.name())
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
            logger.info("SLD saved: %s", path)
            return True
        except Exception as exc:
            logger.error("save_sld error: %s", exc)
            return False

    @staticmethod
    def embed_style_in_gpkg(layer: QgsMapLayer, gpkg_path: str,
                            table_name: str) -> bool:
        """
        Write the layer's current style into the ``layer_styles`` table
        of an existing GeoPackage.

        We load a temporary view of the just-written table, apply the
        source layer's renderer / labeling to it, then call
        ``saveStyleToDatabase``.
        """
        if not isinstance(layer, QgsVectorLayer):
            logger.info("GPKG style embed skipped for raster %s", layer.name())
            return False
        try:
            uri = f"{gpkg_path}|layername={table_name}"
            tmp = QgsVectorLayer(uri, table_name, "ogr")
            if not tmp.isValid():
                logger.warning("Could not open %s|layername=%s for style embed",
                               gpkg_path, table_name)
                return False

            # Copy renderer from source → temporary layer
            if layer.renderer():
                tmp.setRenderer(layer.renderer().clone())
            if layer.labeling():
                tmp.setLabeling(layer.labeling().clone())

            # saveStyleToDatabase(name, description, useAsDefault, uiFileContent)
            err = tmp.saveStyleToDatabase(table_name, "", True, "")
            if err:
                logger.warning("saveStyleToDatabase error for %s: %s",
                               table_name, err)
                return False
            logger.info("Style embedded in GPKG for layer %s", table_name)
            return True
        except Exception as exc:
            logger.error("embed_style_in_gpkg error: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Convenience dispatcher                                               #
    # ------------------------------------------------------------------ #

    def apply_style_mode(self, source_layer: QgsMapLayer,
                         style_mode: str,
                         output_file_path: str,
                         gpkg_table_name: str = "") -> None:
        """
        Dispatch to the right saver(s) based on ``style_mode``.

        Parameters
        ----------
        source_layer : QgsMapLayer
            The original project layer from which styles are read.
        style_mode : str
            One of 'none', 'qml', 'sld', 'both', 'embed'.
        output_file_path : str
            Full path to the written output file (used to build sidecar paths).
        gpkg_table_name : str
            Table / layer name inside the GeoPackage (used for 'embed').
        """
        if style_mode == "none":
            return

        base = os.path.splitext(output_file_path)[0]

        if style_mode in ("qml", "both"):
            self.save_qml(source_layer, base)

        if style_mode in ("sld", "both"):
            self.save_sld(source_layer, base)

        if style_mode == "embed":
            self.embed_style_in_gpkg(
                source_layer, output_file_path, gpkg_table_name
            )
