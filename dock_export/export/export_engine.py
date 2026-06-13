"""Core export engine. Dispatches ExportSpec objects to vector (OGR) or raster (GDAL) writers."""

from __future__ import annotations

import logging
import os
import uuid

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
    QgsField,
    QgsFields,
    QgsMapLayer,
    QgsProject,
    QgsRasterBlockFeedback,
    QgsRectangle,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsRasterProjector,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..models import ExportResult, ExportSpec, StyleMode
from .style_manager import StyleManager

try:
    from osgeo import gdal

    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False

logger = logging.getLogger("DockExport.ExportEngine")


def layer_export_block_reason(layer: QgsMapLayer) -> str:
    """Return a reason string if the layer cannot be exported, or empty string if it can."""
    if isinstance(layer, (QgsRasterLayer, QgsVectorLayer)):
        return ""
    return "This layer type is not supported by the exporter."


class ExportEngine:
    """Executes ExportSpec objects: vectors via QgsVectorFileWriter, rasters via GDAL Translate."""

    def __init__(self, style_manager: StyleManager | None = None):
        self._style = style_manager or StyleManager()
        self._cancel_requested = False

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def cancel_export(self) -> None:
        """Request cancellation after the current spec finishes."""
        self._cancel_requested = True

    def run(self, specs: list[ExportSpec], progress_cb=None) -> list[ExportResult]:
        """Execute a list of ExportSpec objects. Returns a list of ExportResult."""
        self._cancel_requested = False
        results: list[ExportResult] = []
        total = len(specs)

        for i, spec in enumerate(specs):
            if self._cancel_requested:
                break

            msg = f"Exporting '{spec.export_name}'..."
            if progress_cb:
                progress_cb(i, total, msg)

            result = self._export_one(spec)
            results.append(result)

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
        """Write a vector layer to a single file or GPKG table."""
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
        opts.fileEncoding = spec.encoding
        opts.layerName = spec.export_name
        opts.actionOnExistingFile = action
        opts.symbologyExport = Qgis.FeatureSymbologyExport.NoSymbology

        if spec.datasource_options:
            opts.datasourceOptions = spec.datasource_options
        layer_opts = list(spec.layer_options) if spec.layer_options else []
        if spec.description:
            layer_opts.insert(0, f"DESCRIPTION={spec.description}")
        if spec.layer_fid:
            layer_opts.insert(0, f"FID={spec.layer_fid}")
        if spec.geometry_name:
            layer_opts.insert(0, f"GEOMETRY_NAME={spec.geometry_name}")
        if spec.identifier:
            layer_opts.insert(0, f"IDENTIFIER={spec.identifier}")
        if spec.spatial_index:
            layer_opts.insert(0, f"SPATIAL_INDEX={spec.spatial_index}")
        if layer_opts:
            opts.layerOptions = layer_opts

        opts.skipAttributeCreation = spec.skip_attribute_creation

        if spec.filter_extent:
            parts = spec.filter_extent.split(",")
            if len(parts) == 4:
                try:
                    opts.filterExtent = QgsRectangle(
                        float(parts[0]),
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                    )
                except (ValueError, TypeError):
                    pass

        transform_ctx = QgsProject.instance().transformContext()

        target_crs = self._resolve_target_crs(layer, spec, result)
        if target_crs is None:
            return

        if spec.driver in {"GeoRSS", "GML", "KML"} and target_crs.authid() != "EPSG:4326":
            target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        no_attribute_drivers = {"DXF", "DGN"}

        rss_compatible_fields: set[str] = {
            "title",
            "description",
            "link",
            "author",
            "author_name",
            "author_email",
            "author_link",
            "category",
            "category_label",
            "category_scheme",
            "comments",
            "pubdate",
            "source",
            "source_url",
            "guid",
            "guid_permalink",
        }

        needs_no_attributes = spec.driver in no_attribute_drivers or spec.skip_attribute_creation
        has_geom_overrides = bool(
            spec.geometry_type_override or spec.force_z or spec.force_multi,
        )
        use_safe_clone = (
            bool(spec.filter_expression.strip())
            or target_crs != layer.crs()
            or bool(spec.field_names)
            or needs_no_attributes
            or spec.save_selected_only
            or has_geom_overrides
            or bool(spec.field_export_names)
        )

        clone_field_names = spec.field_names
        if needs_no_attributes:
            clone_field_names = []
        elif spec.driver == "GeoRSS":
            compatible = [
                f.name() for f in layer.fields() if f.name().lower() in rss_compatible_fields
            ]
            clone_field_names = compatible
            use_safe_clone = True
        elif spec.driver == "GPX":
            clone_field_names = [f.name() for f in layer.fields() if f.name().lower() != "fid"]
            use_safe_clone = True

        if use_safe_clone:
            source, n_feats, clone_error = self._make_filtered_clone(
                layer,
                spec.filter_expression if spec.filter_expression.strip() else "",
                spec.driver,
                target_crs.authid(),
                field_names=clone_field_names,
                field_types=spec.field_types,
                field_export_names=spec.field_export_names,
                selected_only=spec.save_selected_only,
                use_aliases_for_names=spec.use_aliases_for_export_name,
                geometry_type_override=spec.geometry_type_override,
                force_z=spec.force_z,
                force_multi=spec.force_multi,
                include_constraints=spec.include_constraints,
            )
            if source is None:
                result.error = clone_error or "Could not build filtered/safe clone"
                return
            result.features_written = n_feats
            write_source = source
        else:
            write_source = layer
            result.features_written = layer.featureCount()

        writer = QgsVectorFileWriter.create(
            output_path,
            write_source.fields(),
            write_source.wkbType(),
            write_source.crs(),
            transform_ctx,
            opts,
            (
                QgsFeatureSink.SinkFlags(QgsFeatureSink.SinkFlag.RegeneratePrimaryKey)
                if spec.driver == "GPKG" or is_gpkg_mode
                else QgsFeatureSink.SinkFlags()
            ),
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
        needs_z = spec.driver == "DGN"

        def _feature_generator():
            for f in write_source.getFeatures():
                if self._cancel_requested:
                    break
                if needs_reset_id:
                    f.setId(-1)
                if needs_z:
                    geom = f.geometry()
                    if geom:
                        try:
                            if not geom.constGet().is3D():
                                geom.addZValue(0)
                                f.setGeometry(geom)
                        except AttributeError:
                            pass
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
            if spec.style_mode not in (StyleMode.NONE, StyleMode.EMBED):
                self._style.apply_style_mode(
                    layer,
                    spec.style_mode,
                    output_path,
                    spec.export_name,
                )
        elif spec.style_mode not in (StyleMode.NONE, StyleMode.EMBED):
            self._style.apply_style_mode(layer, spec.style_mode, output_path)

    def _export_raster(
        self,
        layer: QgsRasterLayer,
        spec: ExportSpec,
        result: ExportResult,
    ) -> None:
        """Dispatch raster export to single file or GPKG based on target_mode."""
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
        _transform_ctx: QgsCoordinateTransformContext,
    ) -> None:
        """Export raster to a single file via GDAL Translate."""
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
            ("context:", "wms:", "xyz:", "wmts:", "http://", "https://"),
        ):
            result.error = "Non-file raster providers are not supported yet"
            return

        try:
            gdal.UseExceptions()
            src_ds = gdal.Open(src_path)
            if src_ds is None:
                result.error = f"GDAL could not open raster source: {src_path}"
                return

            drv = gdal.GetDriverByName(spec.driver)
            if drv is None:
                result.error = f"Raster driver '{spec.driver}' not found"
                return

            crs = spec.target_crs_authid.strip()
            if spec.driver == "MBTiles" and crs and crs not in ("EPSG:4326", "EPSG:3857"):
                crs = "EPSG:4326"

            translate_kwargs: dict = {"format": spec.driver}
            if crs:
                translate_kwargs["outputSRS"] = crs

            if spec.filter_extent:
                parts = spec.filter_extent.split(",")
                if len(parts) == 4:
                    try:
                        xmin, ymin, xmax, ymax = (
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
                        translate_kwargs["projWin"] = [xmin, ymax, xmax, ymin]
                    except (ValueError, TypeError):
                        pass

            if spec.raster_resolution_x > 0:
                translate_kwargs["xRes"] = spec.raster_resolution_x
            if spec.raster_resolution_y > 0:
                translate_kwargs["yRes"] = spec.raster_resolution_y

            if spec.raster_nodata:
                translate_kwargs["srcNoData"] = spec.raster_nodata
                translate_kwargs["dstNodata"] = spec.raster_nodata

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
        _transform_ctx: QgsCoordinateTransformContext,
    ) -> None:
        """Embed a raster into a GeoPackage via GDAL Translate with RASTER_TABLE."""
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
            ("context:", "wms:", "xyz:", "wmts:", "http://", "https://"),
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

            translate_kwargs: dict = {
                "format": "GPKG",
                "creationOptions": creation_opts,
            }
            if spec.target_crs_authid.strip():
                translate_kwargs["outputSRS"] = spec.target_crs_authid.strip()

            if spec.filter_extent:
                parts = spec.filter_extent.split(",")
                if len(parts) == 4:
                    try:
                        xmin, ymin, xmax, ymax = (
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
                        translate_kwargs["projWin"] = [xmin, ymax, xmax, ymin]
                    except (ValueError, TypeError):
                        pass

            if spec.raster_resolution_x > 0:
                translate_kwargs["xRes"] = spec.raster_resolution_x
            if spec.raster_resolution_y > 0:
                translate_kwargs["yRes"] = spec.raster_resolution_y

            if spec.raster_nodata:
                translate_kwargs["srcNoData"] = spec.raster_nodata
                translate_kwargs["dstNodata"] = spec.raster_nodata

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
    ) -> tuple[bool, str]:
        """Export any raster (including remote providers like WMS/WMTS) to GPKG via the QGIS rendering pipeline.

        Slower than GDAL Translate for file-based rasters but works with non-file raster providers.
        """
        dp = layer.dataProvider()
        if dp is None:
            return False, "No data provider"

        try:
            dst_crs = target_crs if target_crs and target_crs.isValid() else layer.crs()

            projector = QgsRasterProjector()
            projector.setCrs(
                dp.crs(),
                dst_crs,
                QgsProject.instance().transformContext(),
            )
            pipe = QgsRasterPipe()
            clone = dp.clone()
            if clone is None:
                return False, "Could not clone data provider"
            pipe.set(clone)
            pipe.insert(2, projector)

            tmp_name = uuid.uuid4().hex
            writer = QgsRasterFileWriter(gpkg_path)
            writer.setOutputFormat("GPKG")
            writer.setCreateOptions(
                [
                    f"RASTER_TABLE={tmp_name}",
                    "APPEND_SUBDATASET=YES",
                ],
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

            gdal.UseExceptions()
            src_ds = gdal.OpenEx(gpkg_path, gdal.OF_VECTOR)
            try:
                src_ds.ExecuteSQL(f'ALTER TABLE "{tmp_name}" RENAME TO "{table_name}"')
            finally:
                src_ds = None

            with gdal.OpenEx(gpkg_path, gdal.OF_UPDATE) as ds:
                ds.ExecuteSQL(
                    "UPDATE gpkg_contents SET table_name = ?, identifier = ? WHERE table_name = ?",
                    None,
                    [table_name, table_name, tmp_name],
                )

            return True, ""  # noqa: TRY300

        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _make_filtered_clone(
        layer: QgsVectorLayer,
        expression: str,
        driver_name: str = "",
        target_crs_authid: str = "",
        field_names: list[str] | None = None,
        field_types: dict[str, str] | None = None,
        field_export_names: dict[str, str] | None = None,
        selected_only: bool = False,
        use_aliases_for_names: bool = False,
        geometry_type_override: str = "",
        force_z: bool = False,
        force_multi: bool = False,
        include_constraints: bool = False,
    ) -> tuple[QgsVectorLayer | None, int, str]:
        """Create an in-memory vector layer clone with filter, CRS reprojection,
        field subset, type overrides, and geometry overrides."""
        from qgis.PyQt.QtCore import QVariant

        _GEOM_MAP = {
            "Point": QgsWkbTypes.Type.Point,
            "LineString": QgsWkbTypes.Type.LineString,
            "Polygon": QgsWkbTypes.Type.Polygon,
            "GeometryCollection": QgsWkbTypes.Type.GeometryCollection,
            "NoGeometry": QgsWkbTypes.Type.NoGeometry,
        }

        _TYPE_MAP = {
            "Integer": QVariant.Int,
            "Integer64": QVariant.LongLong,
            "Double": QVariant.Double,
            "String": QVariant.String,
            "Date": QVariant.Date,
            "DateTime": QVariant.DateTime,
            "Time": QVariant.Time,
            "Boolean": QVariant.Bool,
        }

        source_fields = layer.fields()
        kept_indexes = []
        kept_fields = QgsFields()

        for idx, field in enumerate(source_fields):
            if field.name().lower() == "fid":
                continue
            if field_names is not None and field.name() not in field_names:
                continue
            kept_indexes.append(idx)
            fname = field_export_names.get(field.name()) if field_export_names else None
            if fname is None and use_aliases_for_names:
                fname = field.alias()
            if not fname:
                fname = field.name()
            if field_types and field.name() in field_types:
                qtype = _TYPE_MAP.get(field_types[field.name()], QVariant.String)
                new_field = QgsField(fname, qtype)
                if include_constraints:
                    new_field.setConstraints(field.constraints())
                kept_fields.append(new_field)
            elif fname != field.name():
                new_field = QgsField(fname, field.type())
                if include_constraints:
                    new_field.setConstraints(field.constraints())
                kept_fields.append(new_field)
            else:
                kept_fields.append(field)

        target_crs = layer.crs()
        if target_crs_authid.strip():
            requested = QgsCoordinateReferenceSystem(target_crs_authid.strip())
            if not requested.isValid():
                return None, 0, f"Invalid target CRS: {target_crs_authid}"
            target_crs = requested

        wkb_type = layer.wkbType()
        if geometry_type_override and geometry_type_override in _GEOM_MAP:
            wkb_type = _GEOM_MAP[geometry_type_override]
        if force_z:
            wkb_type = QgsWkbTypes.addZ(wkb_type)
        if force_multi:
            wkb_type = QgsWkbTypes.addMulti(wkb_type)
        geom_type = QgsWkbTypes.displayString(wkb_type)
        uri = f"{geom_type}?crs={target_crs.authid()}"
        mem = QgsVectorLayer(uri, "filtered_clone", "memory")
        if not mem.isValid():
            return None, 0, "Could not create memory clone layer"

        dp = mem.dataProvider()
        dp.addAttributes(list(kept_fields))
        mem.updateFields()

        if selected_only:
            features = layer.selectedFeatures()
            if expression.strip():
                expr = QgsExpression(expression)
                if expr.hasParserError():
                    return None, 0, expr.parserErrorString()
                features = [f for f in features if expr.evaluate(f)]
            iterator = iter(features)
        elif expression.strip():
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
            if (
                transform is not None
                and geom is not None
                and not geom.isNull()
                and geom.transform(transform) != 0
            ):
                return None, 0, "Geometry transformation failed"
            if force_z and geom is not None and not geom.isNull():
                try:
                    if not geom.constGet().is3D():
                        geom.get().addZValue(0)
                except (AttributeError, TypeError):
                    pass
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
    ) -> QgsCoordinateReferenceSystem | None:
        """Return the target CRS from spec, or fall back to the source layer CRS."""
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
        """Repoint the project layer to the newly written export file."""
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
                "Could not replace data source for '%s': %s",
                layer.name(),
                exc,
            )
