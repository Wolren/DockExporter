"""Dock Export plugin for QGIS — spec-driven layer export to single files, GeoPackage, and .woof/ZIP archives."""

from .plugin import DockExportPlugin


def classFactory(iface):
    """Load DockExportPlugin when QGIS starts."""
    return DockExportPlugin(iface)
