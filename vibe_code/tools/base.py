from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-neutral description of an agent tool."""

    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str


class AgentTool(Protocol):
    name: str
    description: str
    parameters: dict[str, object]

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        ...
