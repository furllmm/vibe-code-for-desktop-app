from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..tools.base import ToolDefinition


@dataclass(frozen=True)
class AgentMessage:
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple["ToolCall", ...] = ()


@dataclass(frozen=True)
class ProviderRequest:
    messages: list[AgentMessage]
    tools: tuple[ToolDefinition, ...] = ()


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()


class AIProvider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        ...
