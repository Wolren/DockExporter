"""
export_engine.py  –  Spec-driven export engine.

Vector:
  * uses QgsVectorFileWriter.create(...) for both single-file and GPKG
  * always regenerates PK for GPKG via QgsFeatureSink.RegeneratePrimaryKey
  * never renames live layers; names only stored in ExportSpec

Raster:
  * uses pure GDAL.Translate from the layer source
  * for single-file: converts to GTiff/PNG/etc
  * for GPKG: uses RASTER_TABLE + APPEND_SUBDATASET=YES
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import List, Optional, Tuple

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsDataProvider,
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .models import ExportSpec
from .style_manager import StyleManager

try:
    from osgeo import gdal
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False

logger = logging.getLogger("DockExport.ExportEngine")


class ExportResult:
    def __init__(self, spec: ExportSpec):
        self.spec = spec
        self.success: bool = False
        self.output_path: str = ""
        self.error: str = ""
        self.features_written: int = 0

    def __repr__(self):
        return (f"ExportResult(name={self.spec.export_name!r}, "
                f"ok={self.success}, err={self.error!r})")


class ExportEngine:
    """Executes a list of ExportSpec objects.

    Vector:
      * use QgsVectorFileWriter.create
    Raster:
      * use GDAL.Translate
    """

    def __init__(self, style_manager: Optional[StyleManager] = None):
        self._style = style_manager or StyleManager()

    def run(self, specs: List[ExportSpec], progress_cb=None) -> List[ExportResult]:
        results: List[ExportResult] = []
        total = len(specs)

        for i, spec in enumerate(specs):
            msg = f"Exporting '{spec.export_name}'…"
            if progress_cb:
                progress_cb(i, total, msg)
            logger.info(msg)

            result = self._export_one(spec)
            results.append(result)

            if result.success and spec.replace_in_project:
                self._replace_project_source(spec, result)

        if progress_cb:
            progress_cb(total, total, "Done")
        return results

    def _export_one(self, spec: ExportSpec) -> ExportResult:
        result = ExportResult(spec)
        layer = QgsProject.instance().mapLayer(spec.source_layer_id)
        if layer is None or not layer.isValid():
            result.error = f"Layer ID '{spec.source_layer_id}' not found or invalid"
            return result

        try:
            if isinstance(layer, QgsRasterLayer):
                self._export_raster(layer, spec, result)
            elif isinstance(layer, QgsVectorLayer):
                if spec.target_mode == "gpkg":
                    self._export_vector_to_gpkg(layer, spec, result)
                else:
                    self._export_vector_single(layer, spec, result)
            else:
                result.error = "Unsupported layer type"
        except Exception as exc:
            result.error = str(exc)
            logger.exception("Export failed for %s", spec.export_name)

        return result

    # -------------------- VECTOR SINGLE FILE --------------------
    def _export_vector_single(
        self,
        layer: QgsVectorLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        output_path = os.path.join(
            spec.output_path,
            f"{spec.export_name}{spec.file_extension}",
        )
        os.makedirs(spec.output_path, exist_ok=True)

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = spec.driver
        opts.fileEncoding = "UTF-8"
        opts.layerName = spec.export_name
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        opts.symbologyExport = QgsVectorFileWriter.NoSymbology

        transform_ctx = QgsProject.instance().transformContext()

        use_safe_clone = bool(spec.filter_expression.strip()) or spec.driver == "GPKG"
        source = layer

        if use_safe_clone:
            source, n_feats = self._make_filtered_clone(
                layer,
                spec.filter_expression if spec.filter_expression.strip() else "",
                spec.driver,
            )
            if source is None:
                result.error = "Could not build filtered/safe clone"
                return
            result.features_written = n_feats
        else:
            result.features_written = layer.featureCount()

        sink_flags = QgsFeatureSink.SinkFlags()
        if spec.driver == "GPKG":
            sink_flags |= QgsFeatureSink.RegeneratePrimaryKey

        new_filename = ""
        new_layer = ""

        writer = QgsVectorFileWriter.create(
            output_path,
            source.fields(),
            source.wkbType(),
            source.crs(),
            transform_ctx,
            opts,
            sink_flags,
            new_filename,
            new_layer,
        )

        if writer is None:
            result.error = "QgsVectorFileWriter.create() returned None"
            return

        if writer.hasError() != QgsVectorFileWriter.NoError:
            result.error = writer.errorMessage()
            del writer
            return

        for feat in source.getFeatures():
            new_feat = QgsFeature(feat)
            if spec.driver == "GPKG":
                new_feat.setId(-1)
            ok = writer.addFeature(new_feat, QgsFeatureSink.FastInsert)
            if not ok:
                result.error = writer.errorMessage() or "Failed while adding features"
                del writer
                return

        del writer

        result.success = True
        result.output_path = output_path

        if spec.style_mode not in ("none", "embed"):
            self._style.apply_style_mode(layer, spec.style_mode, output_path)
        elif spec.style_mode == "embed" and spec.driver == "GPKG":
            self._style.apply_style_mode(
                layer, "embed", output_path, spec.export_name
            )

    # -------------------- VECTOR → GPKG --------------------
    def _export_vector_to_gpkg(
        self,
        layer: QgsVectorLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        gpkg_path = spec.output_path
        os.makedirs(os.path.dirname(gpkg_path) or ".", exist_ok=True)

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.fileEncoding = "UTF-8"
        opts.layerName = spec.export_name

        if os.path.exists(gpkg_path):
            opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        transform_ctx = QgsProject.instance().transformContext()

        source, n_feats = self._make_filtered_clone(
            layer,
            spec.filter_expression if spec.filter_expression.strip() else "",
            "GPKG",
        )
        if source is None:
            result.error = "Could not build filtered/safe clone"
            return
        result.features_written = n_feats

        sink_flags = QgsFeatureSink.SinkFlags()
        sink_flags |= QgsFeatureSink.RegeneratePrimaryKey

        new_filename = ""
        new_layer = ""

        writer = QgsVectorFileWriter.create(
            gpkg_path,
            source.fields(),
            source.wkbType(),
            source.crs(),
            transform_ctx,
            opts,
            sink_flags,
            new_filename,
            new_layer,
        )

        if writer is None:
            result.error = "QgsVectorFileWriter.create() returned None"
            return

        if writer.hasError() != QgsVectorFileWriter.NoError:
            result.error = writer.errorMessage()
            del writer
            return

        for feat in source.getFeatures():
            new_feat = QgsFeature(feat)
            new_feat.setId(-1)
            ok = writer.addFeature(new_feat, QgsFeatureSink.FastInsert)
            if not ok:
                result.error = writer.errorMessage() or "Failed while adding features"
                del writer
                return

        del writer

        result.success = True
        result.output_path = gpkg_path

        if spec.style_mode not in ("none",):
            embed = spec.style_mode == "embed"
            self._style.apply_style_mode(
                layer,
                "embed" if embed else spec.style_mode,
                gpkg_path,
                spec.export_name,
            )

    # -------------------- RASTER (GDAL) --------------------
    def _export_raster(
        self,
        layer: QgsRasterLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        transform_ctx = QgsProject.instance().transformContext()
        if spec.target_mode == "gpkg":
            self._export_raster_to_gpkg(layer, spec, result, transform_ctx)
        else:
            self._export_raster_single(layer, spec, result, transform_ctx)

    def _export_raster_single(
        self,
        layer: QgsRasterLayer,
        spec: ExportSpec,
        result: ExportResult,
        transform_ctx: QgsCoordinateTransformContext,
    ) -> None:
        if not GDAL_AVAILABLE:
            result.error = "GDAL is required for raster export"
            return

        output_path = os.path.join(
            spec.output_path,
            f"{spec.export_name}{spec.file_extension}",
        )
        os.makedirs(spec.output_path, exist_ok=True)

        src_path = layer.source()
        if not src_path:
            result.error = "Raster layer has no source path"
            return

        if src_path.lower().startswith(("context:", "wms:", "xyz:", "wmts:", "http://", "https://")):
            result.error = "Non-file raster providers are not supported yet"
            return

        try:
            gdal.UseExceptions()
            src_ds = gdal.Open(src_path)
            if src_ds is None:
                result.error = f"GDAL could not open raster source: {src_path}"
                return

            driver_name = "GTiff" if spec.driver == "GTiff" else spec.driver
            gdal.Translate(
                output_path,
                src_ds,
                format=driver_name,
            )
            src_ds = None

            result.success = True
            result.output_path = output_path

            if spec.style_mode in ("qml", "both"):
                self._style.save_qml(layer, os.path.splitext(output_path)[0])

        except Exception as exc:
            result.error = f"GDAL translate error: {exc}"

    def _export_raster_to_gpkg(
        self,
        layer: QgsRasterLayer,
        spec: ExportSpec,
        result: ExportResult,
        transform_ctx: QgsCoordinateTransformContext,
    ) -> None:
        if not GDAL_AVAILABLE:
            result.error = "GDAL is required for raster export to GeoPackage"
            return

        gpkg_path = spec.output_path
        os.makedirs(os.path.dirname(gpkg_path) or ".", exist_ok=True)

        src_path = layer.source()
        if not src_path:
            result.error = "Raster layer has no source path"
            return

        if src_path.lower().startswith(("context:", "wms:", "xyz:", "wmts:", "http://", "https://")):
            result.error = "Non-file raster providers are not supported yet"
            return

        try:
            gdal.UseExceptions()
            src_ds = gdal.Open(src_path)
            if src_ds is None:
                result.error = f"GDAL could not open raster source: {src_path}"
                return

            creation_opts = [
                f"RASTER_TABLE={spec.export_name}",
                "APPEND_SUBDATASET=YES",
            ]

            gdal.Translate(
                gpkg_path,
                src_ds,
                format="GPKG",
                creationOptions=creation_opts,
            )
            src_ds = None

            result.success = True
            result.output_path = gpkg_path

        except Exception as exc:
            result.error = f"GDAL GPKG translate error: {exc}"

    # -------------------- FILTERED CLONE --------------------
    @staticmethod
    def _make_filtered_clone(
        layer: QgsVectorLayer,
        expression: str,
        driver_name: str = "",
    ) -> Tuple[Optional[QgsVectorLayer], int]:
        drop_fid = driver_name.upper() == "GPKG"

        source_fields = layer.fields()
        kept_indexes = []
        kept_fields = QgsFields()

        for idx, field in enumerate(source_fields):
            if drop_fid and field.name().lower() == "fid":
                continue
            kept_indexes.append(idx)
            kept_fields.append(field)

        geom_type = QgsWkbTypes.displayString(layer.wkbType())
        crs_str = layer.crs().authid()
        uri = f"{geom_type}?crs={crs_str}"
        mem = QgsVectorLayer(uri, "filtered_clone", "memory")
        if not mem.isValid():
            logger.error("Could not create memory clone layer")
            return None, 0

        dp = mem.dataProvider()
        dp.addAttributes(list(kept_fields))
        mem.updateFields()

        if expression.strip():
            expr = QgsExpression(expression)
            if expr.hasParserError():
                logger.error("Filter expression parser error: %s", expr.parserErrorString())
                return None, 0
            request = QgsFeatureRequest(expr)
            iterator = layer.getFeatures(request)
        else:
            iterator = layer.getFeatures()

        new_features = []
        for src_feat in iterator:
            feat = QgsFeature(mem.fields())
            feat.setGeometry(src_feat.geometry())
            feat.setAttributes([src_feat[i] for i in kept_indexes])
            feat.setId(-1)
            new_features.append(feat)

        ok, _ = dp.addFeatures(new_features)
        if not ok:
            logger.error("Failed to add filtered features to memory layer")
            return None, 0

        mem.updateExtents()
        logger.info(
            "Filtered clone: %d / %d features kept",
            len(new_features),
            layer.featureCount(),
        )
        return mem, len(new_features)

    # -------------------- REPLACE PROJECT SOURCE --------------------
    @staticmethod
    def _replace_project_source(
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        layer = QgsProject.instance().mapLayer(spec.source_layer_id)
        if layer is None:
            return

        try:
            provider_opts = QgsDataProvider.ProviderOptions()
            provider_opts.transformContext = (
                QgsProject.instance().transformContext()
            )

            if spec.target_mode == "gpkg":
                new_uri = f"{result.output_path}|layername={spec.export_name}"
            else:
                new_uri = result.output_path

            layer.setDataSource(new_uri, layer.name(), "ogr", provider_opts)
            logger.info(
                "Replaced data source for '%s' → %s", layer.name(), new_uri
            )
        except Exception as exc:
            logger.warning(
                "Could not replace data source for '%s': %s",
                layer.name(), exc,
            )
