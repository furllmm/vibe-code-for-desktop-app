import pytest

from vibe_code.editor.selection_analysis import analyze_selection
from vibe_code.providers.base import ProviderResponse


class FakeAnalysisProvider:
    def __init__(self, content):
        self.content = content
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(self.content)


@pytest.mark.parametrize("analysis_type", ["explain", "bugs", "improve"])
def test_selection_analysis_is_read_only_and_includes_bounded_context(analysis_type):
    provider = FakeAnalysisProvider("  Analysis result  ")

    result = analyze_selection(
        provider,
        "src/app.py",
        "return value",
        analysis_type,
        context_before="def calculate():",
        context_after="print(calculate())",
    )

    assert result == "Analysis result"
    prompt = provider.requests[0].messages[1].content
    assert "read-only" in prompt
    assert "src/app.py" in prompt
    assert "return value" in prompt
    assert "def calculate():" in prompt
    assert "print(calculate())" in prompt
    assert provider.requests[0].tools == ()


def test_selection_analysis_rejects_unknown_task_and_empty_selection():
    provider = FakeAnalysisProvider("result")
    with pytest.raises(ValueError, match="Unsupported"):
        analyze_selection(provider, "main.py", "code", "rewrite")
    with pytest.raises(ValueError, match="non-empty"):
        analyze_selection(provider, "main.py", " ", "explain")


def test_selection_analysis_enforces_input_and_output_limits():
    provider = FakeAnalysisProvider("result")
    with pytest.raises(ValueError, match="256 KiB"):
        analyze_selection(provider, "main.py", "x" * (256 * 1024 + 1), "explain")
    with pytest.raises(ValueError, match="32 KiB"):
        analyze_selection(
            FakeAnalysisProvider("x" * (32 * 1024 + 1)),
            "main.py",
            "code",
            "explain",
        )
