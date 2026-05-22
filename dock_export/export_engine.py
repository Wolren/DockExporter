"""Core export engine. Iterates ExportSpec objects and dispatches to vector/raster writers."""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsDataProvider,
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsFields,
    QgsMapLayer,
    QgsProject,
    QgsRasterBlockFeedback,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsRasterProjector,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .models import ExportSpec, ExportResult, StyleMode
from .style_manager import StyleManager

try:
    from osgeo import gdal

    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False

logger = logging.getLogger("DockExport.ExportEngine")


def layer_export_block_reason(layer: QgsMapLayer) -> str:
    """Return reason string if layer cannot be exported, empty string if OK."""
    if isinstance(layer, (QgsRasterLayer, QgsVectorLayer)):
        return ""
    return "This layer type is not supported by the exporter."


class ExportEngine:
    """Executes ExportSpec list: vectors via QgsVectorFileWriter, rasters via GDAL."""

    def __init__(self, style_manager: Optional[StyleManager] = None):
        self._style = style_manager or StyleManager()
        self._cancel_requested = False

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def cancel_export(self) -> None:
        """Request cancellation after the current spec finishes."""
        self._cancel_requested = True

    def run(self, specs: List[ExportSpec], progress_cb=None) -> List[ExportResult]:
        """Execute a list of ExportSpec objects. Returns list of ExportResult."""
        self._cancel_requested = False
        results: List[ExportResult] = []
        total = len(specs)

        for i, spec in enumerate(specs):
            if self._cancel_requested:
                break

            msg = f"Exporting '{spec.export_name}'..."
            if progress_cb:
                progress_cb(i, total, msg)

            result = self._export_one(spec)
            results.append(result)

            if result.success and spec.replace_in_project:
                self._replace_project_source(spec, result)

        if progress_cb:
            progress_cb(
                total if not self._cancel_requested else len(results),
                total,
                "Cancelled" if self._cancel_requested else "Done",
            )
        return results

    def _export_one(self, spec: ExportSpec) -> ExportResult:
        """Export a single layer from a single ExportSpec."""
        result = ExportResult(spec)
        layer = QgsProject.instance().mapLayer(spec.source_layer_id)
        if layer is None or not layer.isValid():
            result.error = f"Layer ID '{spec.source_layer_id}' not found or invalid"
            return result

        block_reason = layer_export_block_reason(layer)
        if block_reason:
            result.error = block_reason
            return result

        try:
            if isinstance(layer, QgsRasterLayer):
                self._export_raster(layer, spec, result)
            elif isinstance(layer, QgsVectorLayer):
                self._export_vector(layer, spec, result)
            else:
                result.error = "Unsupported layer type"
        except Exception as exc:
            result.error = str(exc)

        return result

    def _export_vector(
        self,
        layer: QgsVectorLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        """Write a vector layer to a single file or GPKG table based on target_mode."""
        is_gpkg_mode = spec.target_mode == "gpkg"

        Action = QgsVectorFileWriter.ActionOnExistingFile

        if is_gpkg_mode:
            output_path = spec.output_path
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            action = (
                Action.CreateOrOverwriteLayer
                if os.path.exists(output_path)
                else Action.CreateOrOverwriteFile
            )
        else:
            output_path = os.path.join(
                spec.output_path,
                f"{spec.export_name}{spec.file_extension}",
            )
            os.makedirs(spec.output_path, exist_ok=True)
            action = Action.CreateOrOverwriteFile

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = spec.driver
        opts.fileEncoding = "UTF-8"
        opts.layerName = spec.export_name
        opts.actionOnExistingFile = action
        opts.symbologyExport = Qgis.FeatureSymbologyExport.NoSymbology

        transform_ctx = QgsProject.instance().transformContext()

        target_crs = self._resolve_target_crs(layer, spec, result)
        if target_crs is None:
            return

        use_safe_clone = (
            bool(spec.filter_expression.strip()) or target_crs != layer.crs()
        )

        if use_safe_clone:
            source, n_feats, clone_error = self._make_filtered_clone(
                layer,
                spec.filter_expression if spec.filter_expression.strip() else "",
                spec.driver,
                target_crs.authid(),
                field_names=spec.field_names,
            )
            if source is None:
                result.error = clone_error or "Could not build filtered/safe clone"
                return
            result.features_written = n_feats
            write_source = source
        else:
            write_source = layer
            result.features_written = layer.featureCount()

            # Drop FID for GPKG (always include all other fields)
            if spec.driver == "GPKG" or is_gpkg_mode:
                opts.attributes = [
                    i
                    for i in range(layer.fields().count())
                    if layer.fields()[i].name().lower() != "fid"
                ]

        # Apply per-layer field filter
        if spec.field_names:
            if opts.attributes is not None:
                # Intersect with existing attribute filter (e.g., FID drop)
                existing = set(opts.attributes)
                indices = [
                    i
                    for i in range(layer.fields().count())
                    if layer.fields()[i].name() in spec.field_names and i in existing
                ]
                opts.attributes = indices
            else:
                opts.attributes = [
                    i
                    for i in range(layer.fields().count())
                    if layer.fields()[i].name() in spec.field_names
                ]

        writer = QgsVectorFileWriter.create(
            output_path,
            write_source.fields(),
            write_source.wkbType(),
            write_source.crs(),
            transform_ctx,
            opts,
            QgsFeatureSink.SinkFlags(QgsFeatureSink.SinkFlag.RegeneratePrimaryKey)
            if spec.driver == "GPKG" or is_gpkg_mode
            else QgsFeatureSink.SinkFlags(),
            "",
            "",
        )

        if writer is None:
            result.error = "QgsVectorFileWriter.create() returned None"
            return

        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            result.error = writer.errorMessage()
            del writer
            return

        needs_reset_id = spec.driver == "GPKG" or is_gpkg_mode

        def _feature_generator():
            for f in write_source.getFeatures():
                if self._cancel_requested:
                    break
                if needs_reset_id:
                    f.setId(-1)
                yield f

        ok = writer.addFeatures(_feature_generator())
        if not ok:
            result.error = writer.errorMessage() or "Failed while adding features"
            del writer
            return

        del writer

        result.success = True
        result.output_path = output_path

        if is_gpkg_mode:
            if spec.style_mode != StyleMode.NONE:
                self._style.apply_style_mode(
                    layer,
                    StyleMode.EMBED
                    if spec.style_mode == StyleMode.EMBED
                    else spec.style_mode,
                    output_path,
                    spec.export_name,
                )
        else:
            if spec.style_mode not in (StyleMode.NONE, StyleMode.EMBED):
                self._style.apply_style_mode(layer, spec.style_mode, output_path)
            elif spec.style_mode == StyleMode.EMBED and spec.driver == "GPKG":
                self._style.apply_style_mode(
                    layer, StyleMode.EMBED, output_path, spec.export_name
                )

    def _export_raster(
        self,
        layer: QgsRasterLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        """Dispatch raster export based on target_mode."""
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
        """Export raster to GeoTIFF via GDAL Translate."""
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

        if src_path.lower().startswith(
            ("context:", "wms:", "xyz:", "wmts:", "http://", "https://")
        ):
            result.error = "Non-file raster providers are not supported yet"
            return

        try:
            gdal.UseExceptions()
            src_ds = gdal.Open(src_path)
            if src_ds is None:
                result.error = f"GDAL could not open raster source: {src_path}"
                return

            translate_kwargs = {"format": spec.driver}
            if spec.target_crs_authid.strip():
                translate_kwargs["outputSRS"] = spec.target_crs_authid.strip()
            gdal.Translate(output_path, src_ds, **translate_kwargs)
            src_ds = None

            result.success = True
            result.output_path = output_path

            if spec.style_mode in (StyleMode.QML, StyleMode.BOTH):
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
        """Embed raster into a GeoPackage via GDAL Translate with RASTER_TABLE."""
        if not GDAL_AVAILABLE:
            result.error = "GDAL is required for raster export to GeoPackage"
            return

        gpkg_path = spec.output_path
        os.makedirs(os.path.dirname(gpkg_path) or ".", exist_ok=True)

        src_path = layer.source()
        if not src_path:
            result.error = "Raster layer has no source path"
            return

        if src_path.lower().startswith(
            ("context:", "wms:", "xyz:", "wmts:", "http://", "https://")
        ):
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
            translate_kwargs = {
                "format": "GPKG",
                "creationOptions": creation_opts,
            }
            if spec.target_crs_authid.strip():
                translate_kwargs["outputSRS"] = spec.target_crs_authid.strip()

            gdal.Translate(gpkg_path, src_ds, **translate_kwargs)
            src_ds = None

            result.success = True
            result.output_path = gpkg_path

        except Exception as exc:
            result.error = f"GDAL GPKG translate error: {exc}"

    def export_raster_to_gpkg_via_pipe(
        self,
        layer: QgsRasterLayer,
        gpkg_path: str,
        table_name: str,
        target_crs: QgsCoordinateReferenceSystem = None,
    ) -> Tuple[bool, str]:
        """Export any raster layer (including WMS/WMTS) to GPKG using QGIS raster pipe.

        This works for all raster providers because it uses the QGIS rendering pipeline
        rather than GDAL file access. Slower than GDAL Translate for file-based rasters
        but handles remote layers (WMS, WMTS, XYZ) correctly.
        Returns (success, error_message).
        """
        from osgeo import gdal

        dp = layer.dataProvider()
        if dp is None:
            return False, "No data provider"

        try:
            # Resolve target CRS
            dst_crs = target_crs if target_crs and target_crs.isValid() else layer.crs()

            # Build raster pipe
            projector = QgsRasterProjector()
            projector.setCrs(
                dp.crs(), dst_crs, QgsProject.instance().transformContext()
            )
            pipe = QgsRasterPipe()
            clone = dp.clone()
            if clone is None:
                return False, "Could not clone data provider"
            pipe.set(clone)
            pipe.insert(2, projector)

            # Write to GPKG with temporary name to avoid encoding issues
            import uuid

            tmp_name = uuid.uuid4().hex
            writer = QgsRasterFileWriter(gpkg_path)
            writer.setOutputFormat("GPKG")
            writer.setCreateOptions(
                [
                    f"RASTER_TABLE={tmp_name}",
                    "APPEND_SUBDATASET=YES",
                ]
            )
            feedback = QgsRasterBlockFeedback()
            err = writer.writeRaster(
                pipe,
                dp.xSize(),
                dp.ySize(),
                dp.extent(),
                dst_crs,
                QgsProject.instance().transformContext(),
                feedback,
            )

            if err != QgsRasterFileWriter.WriterError.NoError:
                errors = feedback.errors() or []
                msg = f"Raster pipe write error {err}"
                if errors:
                    msg += f": {'; '.join(str(e) for e in errors)}"
                return False, msg

            # Rename temporary table to desired name
            gdal.UseExceptions()
            src_ds = gdal.OpenEx(gpkg_path, gdal.OF_VECTOR)
            try:
                src_ds.ExecuteSQL(f'ALTER TABLE "{tmp_name}" RENAME TO "{table_name}"')
            finally:
                src_ds = None

            # Update gpkg_contents
            with gdal.OpenEx(gpkg_path, gdal.OF_UPDATE) as ds:
                ds.ExecuteSQL(
                    f"UPDATE gpkg_contents SET table_name = '{table_name}', "
                    f"identifier = '{table_name}' WHERE table_name = '{tmp_name}'"
                )

            return True, ""

        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _make_filtered_clone(
        layer: QgsVectorLayer,
        expression: str,
        driver_name: str = "",
        target_crs_authid: str = "",
        field_names: Optional[List[str]] = None,
    ) -> Tuple[Optional[QgsVectorLayer], int, str]:
        """Create in-memory clone with filter expression and optional CRS reprojection.

        Drops 'fid' field for GPKG driver. Never sets subset string on source.
        *field_names* restricts which attribute columns to include (None = all).
        Returns (memory_layer, feature_count, error_message).
        """
        drop_fid = driver_name.upper() == "GPKG"

        source_fields = layer.fields()
        kept_indexes = []
        kept_fields = QgsFields()

        for idx, field in enumerate(source_fields):
            if drop_fid and field.name().lower() == "fid":
                continue
            if field_names is not None and field.name() not in field_names:
                continue
            kept_indexes.append(idx)
            kept_fields.append(field)

        target_crs = layer.crs()
        if target_crs_authid.strip():
            requested = QgsCoordinateReferenceSystem(target_crs_authid.strip())
            if not requested.isValid():
                return None, 0, f"Invalid target CRS: {target_crs_authid}"
            target_crs = requested

        geom_type = QgsWkbTypes.displayString(layer.wkbType())
        uri = f"{geom_type}?crs={target_crs.authid()}"
        mem = QgsVectorLayer(uri, "filtered_clone", "memory")
        if not mem.isValid():
            return None, 0, "Could not create memory clone layer"

        dp = mem.dataProvider()
        dp.addAttributes(list(kept_fields))
        mem.updateFields()

        if expression.strip():
            expr = QgsExpression(expression)
            if expr.hasParserError():
                return None, 0, expr.parserErrorString()
            iterator = layer.getFeatures(QgsFeatureRequest(expr))
        else:
            iterator = layer.getFeatures()

        transform = None
        if target_crs != layer.crs():
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance().transformContext(),
            )

        new_features = []
        for src_feat in iterator:
            feat = QgsFeature(mem.fields())
            geom = src_feat.geometry()
            if transform is not None and geom is not None and not geom.isNull():
                if geom.transform(transform) != 0:
                    return None, 0, "Geometry transformation failed"
            feat.setGeometry(geom)
            feat.setAttributes([src_feat[i] for i in kept_indexes])
            feat.setId(-1)
            new_features.append(feat)

        ok, _ = dp.addFeatures(new_features)
        if not ok:
            return None, 0, "Failed to add features to memory layer"

        mem.updateExtents()
        return mem, len(new_features), ""

    @staticmethod
    def _resolve_target_crs(
        layer: QgsMapLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> Optional[QgsCoordinateReferenceSystem]:
        """Return target CRS from spec or fall back to source layer CRS."""
        target = spec.target_crs_authid.strip()
        if not target:
            return layer.crs()
        crs = QgsCoordinateReferenceSystem(target)
        if not crs.isValid():
            result.error = f"Invalid target CRS: {target}"
            return None
        return crs

    @staticmethod
    def _replace_project_source(spec: ExportSpec, result: ExportResult) -> None:
        """Repoint project layer to the newly written export file."""
        layer = QgsProject.instance().mapLayer(spec.source_layer_id)
        if layer is None:
            return

        try:
            provider_opts = QgsDataProvider.ProviderOptions()
            provider_opts.transformContext = QgsProject.instance().transformContext()

            if spec.target_mode == "gpkg":
                new_uri = f"{result.output_path}|layername={spec.export_name}"
            else:
                new_uri = result.output_path

            layer.setDataSource(new_uri, layer.name(), "ogr", provider_opts)
        except Exception as exc:
            logger.warning(
                "Could not replace data source for '%s': %s", layer.name(), exc
            )
