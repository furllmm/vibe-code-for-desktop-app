import json

import pytest

from vibe_code.editor.selection_edit import propose_selection_edit
from vibe_code.providers.base import ProviderResponse


class FakeProvider:
    def __init__(self, content):
        self.content = content
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(self.content)


def test_selection_edit_returns_new_document_without_writing():
    source = "def greet():\n    print('hello')\n"
    selected = "print('hello')"
    start = source.index(selected)
    end = start + len(selected)
    provider = FakeProvider(json.dumps({"replacement": "print('hi')"}))

    updated = propose_selection_edit(
        provider, "app.py", source, start, end, "Change the greeting"
    )

    assert updated == "def greet():\n    print('hi')\n"
    assert source == "def greet():\n    print('hello')\n"
    assert selected in provider.requests[0].messages[1].content


def test_selection_edit_handles_unicode_before_selection():
    source = "label = '🙂'\nprint(label)\n"
    selected = "print(label)"
    start = source.index(selected)
    provider = FakeProvider(json.dumps({"replacement": "print('ok')"}))

    updated = propose_selection_edit(
        provider, "app.py", source, start, start + len(selected), "Simplify"
    )

    assert updated == "label = '🙂'\nprint('ok')\n"


@pytest.mark.parametrize("response", ["not json", "{} trailing", '{"replacement": 4}', '{"replacement": "x", "extra": true}'])
def test_selection_edit_rejects_invalid_provider_output(response):
    provider = FakeProvider(response)
    with pytest.raises(ValueError):
        propose_selection_edit(provider, "app.py", "abc", 0, 3, "Change it")


def test_selection_edit_rejects_empty_or_invalid_selection():
    provider = FakeProvider('{"replacement":"x"}')
    with pytest.raises(ValueError, match="instruction"):
        propose_selection_edit(provider, "app.py", "abc", 0, 1, " ")
    with pytest.raises(ValueError, match="Select a non-empty"):
        propose_selection_edit(provider, "app.py", "abc", 1, 1, "Change")
