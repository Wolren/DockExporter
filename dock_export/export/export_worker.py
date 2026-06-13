"""Background export worker. Runs ExportEngine.run() off the main thread."""

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .export_engine import ExportEngine
from ..models import ExportSpec
from .style_manager import StyleManager


class ExportWorker(QObject):
    """Runs a list of ExportSpecs in a background thread.

    Signals
    -------
    progress(current: int, total: int, message: str)
    finished(results: list[ExportResult])
    """

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)

    def __init__(
        self,
        specs: list[ExportSpec],
        style_manager: StyleManager | None = None,
    ):
        super().__init__()
        self.specs = specs
        self.was_cancelled = False
        self._engine = ExportEngine(style_manager or StyleManager())

    def run(self) -> None:
        """Called from the QThread. Emits *finished* when all specs are processed."""
        results = self._engine.run(self.specs, progress_cb=self._on_progress)
        self.was_cancelled = self._engine.cancel_requested
        self.finished.emit(results)

    def cancel(self) -> None:
        """Request cancellation after the current spec completes."""
        self._engine.cancel_export()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        """Forward engine progress to the UI thread."""
        self.progress.emit(current, total, message)
