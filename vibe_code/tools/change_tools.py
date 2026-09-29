from __future__ import annotations

from vibe_code.changes import ChangeManager
from .base import ToolResult


class RollbackChangesTool:
    name = "rollback_changes"
    description = "Rollback a recorded write change set if the target files have not changed since the write."
    parameters = {
        "type": "object",
        "properties": {
            "change_id": {"type": "string", "description": "Recorded change-set identifier."},
        },
        "required": ["change_id"],
        "additionalProperties": False,
    }

    def __init__(self, manager: ChangeManager) -> None:
        self.manager = manager

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        change_id = arguments.get("change_id")
        if not isinstance(change_id, str) or not change_id:
            return ToolResult(False, "change_id must be a non-empty string")
        try:
            change_set = self.manager.rollback(change_id)
            paths = ", ".join(item.path for item in change_set.changes)
            return ToolResult(True, f"Rolled back {change_id}: {paths}")
        except (OSError, KeyError, PermissionError, RuntimeError) as exc:
            return ToolResult(False, f"rollback_changes failed: {exc}")


class GetChangesTool:
    name = "get_changes"
    description = "Show recent recorded file changes and their rollback identifiers."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, manager: ChangeManager) -> None:
        self.manager = manager

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        try:
            changes = self.manager.list_changes()
            if not changes:
                return ToolResult(True, "No recorded changes.")
            lines = [
                f"{change.id}: " + ", ".join(item.path for item in change.changes)
                for change in changes
            ]
            return ToolResult(True, "\n".join(lines))
        except (OSError, RuntimeError) as exc:
            return ToolResult(False, f"get_changes failed: {exc}")
