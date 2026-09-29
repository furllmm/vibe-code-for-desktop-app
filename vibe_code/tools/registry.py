from __future__ import annotations

from .base import AgentTool


class ToolRegistry:
    """Explicit allow-list of tools available to an agent."""

    def __init__(self, tools: tuple[AgentTool, ...] = ()) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)
