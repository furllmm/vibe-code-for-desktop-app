from __future__ import annotations

from dataclasses import dataclass

from ..context.models import ContextPack
from ..providers.base import (
    AgentMessage,
    AIProvider,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)
from ..tools.base import ToolDefinition, ToolResult
from ..tools.registry import ToolRegistry


@dataclass(frozen=True)
class AgentRequest:
    prompt: str
    context: ContextPack


@dataclass(frozen=True)
class ToolExecution:
    call_id: str
    name: str
    result: ToolResult


@dataclass(frozen=True)
class AgentRunResult:
    content: str
    messages: tuple[AgentMessage, ...]
    executions: tuple[ToolExecution, ...]
    turns: int
    stopped_by_limit: bool = False


class AgentService:
    """Build provider-neutral agent requests from user intent and selected context."""

    SYSTEM_PROMPT = (
        "You are a desktop application coding agent. "
        "Use the supplied project context as evidence, make minimal maintainable changes, "
        "and do not assume files or APIs that are not present in the context."
    )

    @classmethod
    def build_messages(cls, request: AgentRequest) -> list[AgentMessage]:
        if not request.prompt.strip():
            raise ValueError("prompt must not be empty")

        context = request.context.as_text()
        user_content = request.prompt.strip()
        if context:
            user_content += (
                "\n\n<project_context>\n"
                + context
                + "\n</project_context>"
            )

        return [
            AgentMessage(role="system", content=cls.SYSTEM_PROMPT),
            AgentMessage(role="user", content=user_content),
        ]

    @classmethod
    def build_provider_request(
        cls,
        request: AgentRequest,
        tools: tuple[ToolDefinition, ...],
    ) -> ProviderRequest:
        return ProviderRequest(cls.build_messages(request), tools)

    @classmethod
    def complete(cls, provider: AIProvider, request: AgentRequest) -> str:
        return provider.complete(
            cls.build_provider_request(request, ())
        ).content


class AgentLoop:
    """Run bounded provider/tool turns through the explicit tool registry."""

    def __init__(
        self,
        provider: AIProvider,
        registry: ToolRegistry,
        *,
        max_turns: int = 8,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns

    def run(self, request: AgentRequest) -> AgentRunResult:
        messages = AgentService.build_messages(request)
        tool_definitions = self.registry.definitions()
        executions: list[ToolExecution] = []

        for turn in range(1, self.max_turns + 1):
            response: ProviderResponse = self.provider.complete(
                ProviderRequest(messages, tool_definitions)
            )

            if not response.tool_calls:
                messages.append(AgentMessage(role="assistant", content=response.content))
                return AgentRunResult(
                    content=response.content,
                    messages=tuple(messages),
                    executions=tuple(executions),
                    turns=turn,
                )

            calls_text = "\n".join(
                f"{call.id}: {call.name}" for call in response.tool_calls
            )
            messages.append(
                AgentMessage(
                    role="assistant",
                    content=response.content or f"Requested tools: {calls_text}",
                )
            )

            for call in response.tool_calls:
                result = self._execute(call)
                executions.append(result)
                messages.append(
                    AgentMessage(
                        role="tool",
                        content=result.result.output,
                        name=result.name,
                        tool_call_id=result.call_id,
                    )
                )

        return AgentRunResult(
            content="Agent stopped after reaching the maximum number of turns.",
            messages=tuple(messages),
            executions=tuple(executions),
            turns=self.max_turns,
            stopped_by_limit=True,
        )

    def _execute(self, call: ToolCall) -> ToolExecution:
        try:
            tool = self.registry.get(call.name)
        except KeyError as exc:
            return ToolExecution(
                call.id,
                call.name,
                ToolResult(False, str(exc)),
            )

        try:
            result = tool.execute(call.arguments)
        except Exception as exc:
            result = ToolResult(False, f"{call.name} failed: {exc}")
        return ToolExecution(call.id, call.name, result)
