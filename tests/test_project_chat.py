from pathlib import Path

import pytest

from vibe_code.chat.project_chat import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_EXCHANGES,
    ProjectChatSession,
)
from vibe_code.context.models import ContextItem, ContextPack, ContextRequest
from vibe_code.providers.base import ProviderResponse
from vibe_code.workspace import Workspace


class FakeContextService:
    def __init__(self):
        self.requests = []

    def build(self, request):
        self.requests.append(request)
        return ContextPack((
            ContextItem(
                request.workspace / "src" / "main.py",
                "file",
                10,
                "matched",
                "def main(): return 42",
                1,
                1,
            ),
        ), 8)


class FakeProvider:
    def __init__(self, answers=None):
        self.answers = list(answers or ["answer"])
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(self.answers.pop(0) if self.answers else "follow-up")


def test_project_chat_retrieves_relevant_context_for_each_turn(tmp_path):
    (tmp_path / "src").mkdir()
    context = FakeContextService()
    provider = FakeProvider(["first answer", "second answer"])
    session = ProjectChatSession(
        provider, Workspace(tmp_path), context_service=context,
        focus_paths=("src/main.py",),
    )

    assert session.ask("Explain the main function") == "first answer"
    assert session.ask("What happens if it returns None?") == "second answer"

    assert len(context.requests) == 2
    assert context.requests[0].prompt == "Explain the main function"
    assert context.requests[0].token_budget == 6000
    assert context.requests[0].focus_paths == (tmp_path / "src" / "main.py",)
    first, second = provider.requests
    assert first.tools == second.tools == ()
    assert first.messages[0].role == "system"
    assert "untrusted" in first.messages[0].content
    assert "src/main.py" in first.messages[1].content
    assert "def main" in first.messages[1].content
    assert "Explain the main function" in second.messages[-3].content
    assert second.messages[-2].content == "first answer"
    assert "What happens if it returns None?" in second.messages[-1].content


def test_project_chat_rejects_invalid_questions_and_focus_escape(tmp_path):
    workspace = Workspace(tmp_path)
    with pytest.raises(ValueError, match="escapes workspace"):
        ProjectChatSession(FakeProvider(), workspace, focus_paths=("../outside.py",))

    provider = FakeProvider()
    session = ProjectChatSession(provider, workspace, context_service=FakeContextService())
    with pytest.raises(ValueError, match="question"):
        session.ask(" ")
    with pytest.raises(ValueError, match="4 KiB"):
        session.ask("x" * (4 * 1024 + 1))
    assert provider.requests == []


def test_project_chat_bounds_history_and_rejects_oversized_answers(tmp_path):
    provider = FakeProvider()
    session = ProjectChatSession(
        provider, Workspace(tmp_path), context_service=FakeContextService()
    )
    for index in range(MAX_HISTORY_EXCHANGES + 3):
        session.ask(f"question {index}")
    history = session.history
    assert len(history) <= MAX_HISTORY_EXCHANGES * 2
    assert len(history) % 2 == 0
    assert sum(len(item.content) for item in history) <= MAX_HISTORY_CHARS

    oversized = FakeProvider(["x" * (32 * 1024 + 1)])
    bad_session = ProjectChatSession(
        oversized, Workspace(tmp_path), context_service=FakeContextService()
    )
    with pytest.raises(ValueError, match="32 KiB"):
        bad_session.ask("Explain")
    assert bad_session.history == ()


def test_project_chat_rejects_workspace_removed_after_session_creation(tmp_path):
    workspace = Workspace(tmp_path)
    session = ProjectChatSession(
        FakeProvider(), workspace, context_service=FakeContextService()
    )
    moved = tmp_path.with_name(tmp_path.name + "-moved")
    tmp_path.rename(moved)
    with pytest.raises(ValueError, match="no longer available"):
        session.ask("Explain project")
