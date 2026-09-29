from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentMessage:
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None


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
    def complete(self, messages: list[AgentMessage]) -> ProviderResponse:
        ...
