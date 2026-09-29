from __future__ import annotations

from ..runtime.preview import PreviewEngine
from .base import ToolResult


class RunPreviewTool:
    name = "run_preview"
    description = "Build and start the configured desktop preview for the current workspace."
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, preview: PreviewEngine) -> None:
        self.preview = preview

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        if arguments:
            return ToolResult(False, "run_preview takes no arguments")
        try:
            self.preview.build()
            self.preview.start()
            return ToolResult(True, "Preview started.")
        except Exception as exc:
            return ToolResult(False, f"run_preview failed: {exc}")


class GetPreviewLogsTool:
    name = "get_preview_logs"
    description = "Read currently buffered stdout/stderr from the desktop preview and report its exit state."
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, preview: PreviewEngine) -> None:
        self.preview = preview

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        if arguments:
            return ToolResult(False, "get_preview_logs takes no arguments")
        try:
            logs = self.preview.read_logs()
            status = self.preview.poll()
            parts = []
            if logs:
                parts.append(logs.rstrip())
            if status is not None:
                parts.append(
                    f"Preview exited with code {status.returncode}; "
                    f"crashed={status.crashed}."
                )
            elif self.preview.running:
                parts.append("Preview is still running.")
            else:
                parts.append("Preview is not running.")
            return ToolResult(True, "\n".join(parts))
        except Exception as exc:
            return ToolResult(False, f"get_preview_logs failed: {exc}")


class StopPreviewTool:
    name = "stop_preview"
    description = "Stop the configured desktop preview process."
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, preview: PreviewEngine) -> None:
        self.preview = preview

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        if arguments:
            return ToolResult(False, "stop_preview takes no arguments")
        try:
            result = self.preview.stop()
            if result is None:
                return ToolResult(True, "Preview was not running.")
            return ToolResult(
                True,
                f"Preview stopped with code {result.returncode}.",
            )
        except Exception as exc:
            return ToolResult(False, f"stop_preview failed: {exc}")
