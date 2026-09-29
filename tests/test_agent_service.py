from pathlib import Path

import pytest

from vibe_code.agent import AgentService
from vibe_code.agent.service import AgentRequest
from vibe_code.context.models import ContextItem, ContextPack


class FakeProvider:
    def __init__(self) -> None:
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        return "ok"


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
    provider = FakeProvider()
    result = AgentService.complete(
        provider,
        AgentRequest("hello", ContextPack((), estimated_tokens=0)),
    )

    assert result == "ok"
    assert provider.messages is not None
    assert len(provider.messages) == 2
