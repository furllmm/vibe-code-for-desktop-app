from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from .engine import PackagingEngine
from .models import PackagingPlan, PackagingResult


class PackagingWorker(QObject):
    """Execute a reviewed packaging plan away from the GUI thread."""

    output = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        engine: PackagingEngine,
        plan: PackagingPlan,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.plan = plan
        self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        try:
            result = self.engine.execute(
                self.plan,
                trusted_workspace=True,
                cancel_event=self.cancel_event,
                on_output=self.output.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)
