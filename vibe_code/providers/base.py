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
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage | None = None


class ProviderError(RuntimeError):
    """Provider failure with a user-safe message (never contains credentials)."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ProviderCancelled(ProviderError):
    def __init__(self) -> None:
        super().__init__("provider request was cancelled")


class AIProvider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        ...
