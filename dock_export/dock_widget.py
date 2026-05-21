"""Dock widget wrapper for the Dock Export plugin interface."""

from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsDockWidget

from .export_widget import ExportWidget


class ExportDockWidget(QgsDockWidget):
    """QgsDockWidget subclass hosting the ExportWidget. Handles close events and layer delegation."""

    def __init__(self, iface, parent=None):
        super().__init__("Dock Export", parent)
        self.setObjectName("DockExportDockWidget")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._export_widget = ExportWidget(iface, parent=self)
        self.setWidget(self._export_widget)

    def closeEvent(self, event) -> None:
        self._export_widget.disconnect_all()
        super().closeEvent(event)

    def set_active_layer(self, layer) -> None:
        """Delegate to ExportWidget to select and scroll to a specific layer."""
        self._export_widget.set_active_layer(layer)
