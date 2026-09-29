from __future__ import annotations

from vibe_code.changes import ChangeManager
from .base import ToolResult
from .filesystem import WorkspaceFS


class ReadFileTool:
    name = "read_file"
    description = "Read a UTF-8 text file inside the current workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, filesystem: WorkspaceFS) -> None:
        self.filesystem = filesystem

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            return ToolResult(False, "path must be a non-empty string")
        try:
            return ToolResult(True, self.filesystem.read_text(path))
        except (OSError, PermissionError, UnicodeError) as exc:
            return ToolResult(False, f"read_file failed: {exc}")


class WriteFileTool:
    name = "write_file"
    description = "Atomically write UTF-8 text inside the workspace and record it for rollback."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "Complete UTF-8 file contents."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        filesystem: WorkspaceFS,
        changes: ChangeManager | None = None,
    ) -> None:
        self.filesystem = filesystem
        self.changes = changes

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(path, str) or not path:
            return ToolResult(False, "path must be a non-empty string")
        if not isinstance(content, str):
            return ToolResult(False, "content must be a string")
        try:
            if self.changes is not None:
                record = self.changes.write_text(path, content)
                return ToolResult(
                    True,
                    f"Wrote {path} (rollback record: {record.after_sha256[:12]})",
                )
            self.filesystem.write_text(path, content)
            return ToolResult(True, f"Wrote {path}")
        except (OSError, PermissionError, UnicodeError, RuntimeError) as exc:
            return ToolResult(False, f"write_file failed: {exc}")
