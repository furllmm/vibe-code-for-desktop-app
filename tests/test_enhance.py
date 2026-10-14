from __future__ import annotations

import pytest

from vibe_code.agent.enhance import EnhancementService
from vibe_code.context.models import ContextPack
from vibe_code.providers.base import ProviderResponse


class FakeProvider:
    def __init__(self, content: str = "## Requirements\n- Keep the requested red button.") -> None:
        self.content = content
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(self.content)


def test_enhance_builds_project_aware_request_without_tools() -> None:
    provider = FakeProvider()
    context = ContextPack((), estimated_tokens=0)

    result = EnhancementService.enhance(provider, "make the button red", context)

    assert "red button" in result
    request = provider.requests[0]
    assert request.tools == ()
    assert "Preserve the user's intent" in request.messages[0].content
    assert "make the button red" in request.messages[1].content


def test_enhance_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError, match="prompt must not be empty"):
        EnhancementService.build_request("  ", ContextPack((), estimated_tokens=0))


def test_enhance_returns_trimmed_text() -> None:
    provider = FakeProvider("  Enhanced brief  \n")
    assert EnhancementService.enhance(
        provider, "improve settings", ContextPack((), estimated_tokens=0)
    ) == "Enhanced brief"
