"""QgsDockWidget wrapper hosting the ExportWidget."""

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt

from .export_widget import ExportWidget


class ExportDockWidget(QgsDockWidget):
    """QgsDockWidget subclass hosting the ExportWidget. Handles close events and layer delegation."""

    def __init__(self, iface, parent=None):
        super().__init__("Dock Export", parent)
        self.setObjectName("DockExportDockWidget")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea,
        )

        self._export_widget = ExportWidget(iface, parent=self)
        self.setWidget(self._export_widget)

    def closeEvent(self, event) -> None:
        """Persist settings and disconnect project signals before closing."""
        self._export_widget.disconnect_all()
        super().closeEvent(event)

    def set_active_layer(self, layer) -> None:
        """Select and scroll to *layer* in the export table."""
        self._export_widget.set_active_layer(layer)
