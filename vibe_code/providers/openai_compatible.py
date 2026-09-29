from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from .base import AgentMessage, AIProvider, ProviderRequest, ProviderResponse, ToolCall


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Configuration for providers exposing a Chat Completions-compatible API."""

    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 60.0

    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


class OpenAICompatibleProvider:
    """Small provider adapter; no vendor SDK is required."""

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        if not config.base_url.strip():
            raise ValueError("base_url must not be empty")
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if config.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.config = config

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        payload = {
            "model": self.config.model,
            "messages": [self._message(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        http_request = urllib_request.Request(
            self.config.endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(http_request, timeout=self.config.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"provider HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"provider connection failed: {exc.reason}") from exc

        return self._parse_response(raw)

    @staticmethod
    def _message(message: AgentMessage) -> dict[str, object]:
        result: dict[str, object] = {"role": message.role, "content": message.content}
        if message.name:
            result["name"] = message.name
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        return result

    @staticmethod
    def _parse_response(raw: bytes) -> ProviderResponse:
        try:
            data = json.loads(raw.decode("utf-8"))
            message = data["choices"][0]["message"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("provider returned an invalid Chat Completions response") from exc

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise RuntimeError("provider response content must be a string")

        calls: list[ToolCall] = []
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise RuntimeError("provider response tool_calls must be a list")

        for raw_call in raw_calls:
            try:
                function = raw_call["function"]
                call_id = raw_call["id"]
                name = function["name"]
                arguments = function.get("arguments", "{}")
                parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("provider returned an invalid tool call") from exc
            if not isinstance(call_id, str) or not isinstance(name, str):
                raise RuntimeError("provider tool call id and name must be strings")
            if not isinstance(parsed_arguments, dict):
                raise RuntimeError("provider tool call arguments must be a JSON object")
            calls.append(ToolCall(call_id, name, parsed_arguments))

        return ProviderResponse(content, tuple(calls))
