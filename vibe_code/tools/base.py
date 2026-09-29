from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str


class AgentTool(Protocol):
    name: str
    description: str

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        ...
