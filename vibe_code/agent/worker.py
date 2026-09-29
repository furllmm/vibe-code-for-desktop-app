from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .service import AgentRequest, AgentRunResult, AgentLoop


class AgentWorker(QObject):
    """Run an agent loop outside the Qt GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, loop: AgentLoop, request: AgentRequest) -> None:
        super().__init__()
        self.loop = loop
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            result = self.loop.run(self.request)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)
