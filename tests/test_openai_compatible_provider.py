import json

import pytest

from vibe_code.providers.base import AgentMessage, ProviderRequest
from vibe_code.providers.openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider
from vibe_code.tools.base import ToolDefinition


def test_provider_builds_chat_completion_payload(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data)
        return Response()

    monkeypatch.setattr("vibe_code.providers.openai_compatible.urllib_request.urlopen", fake_urlopen)
    tool = ToolDefinition("read_file", "Read a file.", {"type": "object", "properties": {"path": {"type": "string"}}})
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig("http://localhost:8000/v1", "local-model", "secret"))
    result = provider.complete(ProviderRequest([AgentMessage("system", "system"), AgentMessage("user", "hello")], (tool,)))

    assert result.content == "hello"
    assert captured["url"] == "http://localhost:8000/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["payload"]["model"] == "local-model"
    assert captured["payload"]["tools"][0]["function"]["name"] == "read_file"


def test_provider_parses_structured_tool_calls(monkeypatch) -> None:
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "Inspecting.", "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'}
            }]}}]}).encode()

    monkeypatch.setattr("vibe_code.providers.openai_compatible.urllib_request.urlopen", lambda req, timeout: Response())
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig("http://localhost:8000/v1", "local-model"))
    result = provider.complete(ProviderRequest([AgentMessage("user", "inspect")]))

    assert result.content == "Inspecting."
    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "main.py"}


def test_provider_rejects_invalid_tool_arguments(monkeypatch) -> None:
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "", "tool_calls": [{
                "id": "call-1", "function": {"name": "read_file", "arguments": "[]"}
            }]}}]}).encode()

    monkeypatch.setattr("vibe_code.providers.openai_compatible.urllib_request.urlopen", lambda req, timeout: Response())
    provider = OpenAICompatibleProvider(OpenAICompatibleConfig("http://localhost:8000/v1", "local-model"))

    with pytest.raises(RuntimeError, match="arguments must be a JSON object"):
        provider.complete(ProviderRequest([AgentMessage("user", "inspect")]))
