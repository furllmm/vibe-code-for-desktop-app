from pathlib import Path

import pytest

from vibe_code.agent import AgentService
from vibe_code.agent.service import AgentLoop, AgentRequest
from vibe_code.context.models import ContextItem, ContextPack
from vibe_code.providers.base import ProviderRequest, ProviderResponse, ToolCall
from vibe_code.tools.base import ToolResult
from vibe_code.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, request: ProviderRequest):
        self.requests.append(request)
        return self.responses.pop(0)


class EchoTool:
    name = "echo"
    description = "Echo text."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, arguments):
        value = arguments.get("text")
        if not isinstance(value, str):
            return ToolResult(False, "text must be a string")
        return ToolResult(True, value)


def test_agent_builds_messages_with_context(tmp_path: Path) -> None:
    item = ContextItem(
        path=tmp_path / "main.py",
        kind="file",
        score=10,
        reason="name:main",
        content="def main():\n    return 1\n",
        start_line=1,
        end_line=2,
    )
    request = AgentRequest(
        "Fix the main function",
        ContextPack((item,), estimated_tokens=10),
    )

    messages = AgentService.build_messages(request)

    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "Fix the main function" in messages[1].content
    assert "<project_context>" in messages[1].content
    assert "(L1-2)" in messages[1].content
    assert "def main" in messages[1].content


def test_agent_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError):
        AgentService.build_messages(
            AgentRequest("  ", ContextPack((), estimated_tokens=0))
        )


def test_agent_complete_delegates_to_provider() -> None:
    provider = FakeProvider([ProviderResponse("ok")])
    result = AgentService.complete(
        provider,
        AgentRequest("hello", ContextPack((), estimated_tokens=0)),
    )

    assert result == "ok"
    assert len(provider.requests) == 1
    assert len(provider.requests[0].messages) == 2
    assert provider.requests[0].tools == ()


def test_agent_loop_passes_registered_tool_definitions() -> None:
    provider = FakeProvider([ProviderResponse("Done.")])
    registry = ToolRegistry((EchoTool(),))

    result = AgentLoop(provider, registry).run(
        AgentRequest("inspect", ContextPack((), estimated_tokens=0))
    )

    assert result.content == "Done."
    assert len(provider.requests) == 1
    assert len(provider.requests[0].tools) == 1
    definition = provider.requests[0].tools[0]
    assert definition.name == "echo"
    assert definition.description == "Echo text."
    assert definition.parameters["required"] == ["text"]


def test_agent_loop_executes_tool_and_returns_final_response() -> None:
    provider = FakeProvider(
        [
            ProviderResponse(
                "I need to inspect this first.",
                (ToolCall("1", "echo", {"text": "tool result"}),),
            ),
            ProviderResponse("Done."),
        ]
    )
    result = AgentLoop(provider, ToolRegistry((EchoTool(),))).run(
        AgentRequest("inspect", ContextPack((), estimated_tokens=0))
    )

    assert result.content == "Done."
    assert result.turns == 2
    assert len(result.executions) == 1
    assert result.executions[0].result.ok
    assert result.executions[0].result.output == "tool result"
    assert provider.requests[1].messages[-1].role == "tool"
    assert provider.requests[1].messages[-1].tool_call_id == "1"


def test_agent_loop_rejects_unknown_tool_without_crashing() -> None:
    provider = FakeProvider(
        [
            ProviderResponse("", (ToolCall("1", "missing", {}),)),
            ProviderResponse("Recovered."),
        ]
    )
    result = AgentLoop(provider, ToolRegistry()).run(
        AgentRequest("inspect", ContextPack((), estimated_tokens=0))
    )

    assert result.content == "Recovered."
    assert not result.executions[0].result.ok
    assert "Unknown agent tool" in result.executions[0].result.output


def test_agent_loop_stops_at_turn_limit() -> None:
    provider = FakeProvider(
        [
            ProviderResponse("", (ToolCall(str(i), "echo", {"text": "x"}),))
            for i in range(3)
        ]
    )
    result = AgentLoop(provider, ToolRegistry((EchoTool(),)), max_turns=2).run(
        AgentRequest("loop", ContextPack((), estimated_tokens=0))
    )

    assert result.stopped_by_limit
    assert result.turns == 2
    assert len(provider.requests) == 2
