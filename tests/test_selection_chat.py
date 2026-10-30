import pytest

from vibe_code.editor.selection_chat import (
    MAX_HISTORY_EXCHANGES,
    MAX_HISTORY_CHARS,
    SelectionChatSession,
)
from vibe_code.providers.base import ProviderResponse


class FakeProvider:
    def __init__(self, answers=None):
        self.answers = list(answers or ["answer"])
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(self.answers.pop(0) if self.answers else "follow-up")


def test_selection_chat_keeps_source_snapshot_and_follow_up_history():
    provider = FakeProvider(["first answer", "second answer"])
    session = SelectionChatSession(
        provider, "src/app.py", "return value",
        context_before="def run():", context_after="run()",
    )

    assert session.ask("What does this return?") == "first answer"
    assert session.ask("What if value is None?") == "second answer"

    first = provider.requests[0]
    second = provider.requests[1]
    assert first.tools == second.tools == ()
    assert first.messages[0].role == "system"
    assert "src/app.py" in first.messages[1].content
    assert "return value" in first.messages[1].content
    assert second.messages[-3].content == "What does this return?"
    assert second.messages[-2].content == "first answer"
    assert second.messages[-1].content == "What if value is None?"


def test_selection_chat_rejects_empty_question_and_empty_selection():
    provider = FakeProvider()
    with pytest.raises(ValueError, match="non-empty"):
        SelectionChatSession(provider, "main.py", " ")
    session = SelectionChatSession(provider, "main.py", "print(1)")
    with pytest.raises(ValueError, match="question"):
        session.ask("  ")
    assert provider.requests == []


def test_selection_chat_enforces_request_and_response_limits():
    provider = FakeProvider(["x" * (32 * 1024 + 1)])
    with pytest.raises(ValueError, match="256 KiB"):
        SelectionChatSession(provider, "main.py", "x" * (256 * 1024 + 1))
    session = SelectionChatSession(provider, "main.py", "print(1)")
    with pytest.raises(ValueError, match="4 KiB"):
        session.ask("x" * (4 * 1024 + 1))
    with pytest.raises(ValueError, match="32 KiB"):
        session.ask("Explain this")
    assert session.history == ()


def test_selection_chat_bounds_history_to_whole_exchanges():
    provider = FakeProvider()
    session = SelectionChatSession(provider, "main.py", "print(1)")
    for index in range(MAX_HISTORY_EXCHANGES + 4):
        session.ask(f"question {index}")
    history = session.history
    assert len(history) <= MAX_HISTORY_EXCHANGES * 2
    assert len(history) % 2 == 0
    assert sum(len(item.content) for item in history) <= MAX_HISTORY_CHARS
    assert all(item.role in {"user", "assistant"} for item in history)


def test_failed_chat_response_does_not_pollute_history():
    provider = FakeProvider([""])
    session = SelectionChatSession(provider, "main.py", "print(1)")
    with pytest.raises(ValueError, match="empty"):
        session.ask("Explain")
    assert session.history == ()
