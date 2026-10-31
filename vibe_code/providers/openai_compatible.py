from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from ..security import redact_secrets
from .base import (
    AgentMessage,
    ProviderCancelled,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
    ToolCall,
)

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_MAX_ERROR_DETAIL = 500
_MAX_RETRY_AFTER = 60.0


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    """Configuration for providers exposing a Chat Completions-compatible API."""

    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 60.0
    max_retries: int = 2
    retry_backoff: float = 1.0
    redact_secrets: bool = True

    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def models_endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/models"

    def __repr__(self) -> str:
        key = "set" if self.api_key else "unset"
        return f"OpenAICompatibleConfig(base_url={self.base_url!r}, model={self.model!r}, api_key=<{key}>)"


class OpenAICompatibleProvider:
    """Small provider adapter; no vendor SDK is required."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        cancel_event: threading.Event | None = None,
    ) -> None:
        if not config.base_url.strip():
            raise ValueError("base_url must not be empty")
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if config.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if config.max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.config = config
        self.cancel_event = cancel_event or threading.Event()
        self._sleep = sleep
        self.total_usage = TokenUsage()
        self.redactions = 0

    def cancel(self) -> None:
        self.cancel_event.set()

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        payload: dict[str, object] = {
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
        raw = self._send(self.config.endpoint(), json.dumps(payload).encode("utf-8"))
        response = self._parse_response(raw)
        if response.usage is not None:
            self.total_usage = TokenUsage(
                self.total_usage.prompt_tokens + response.usage.prompt_tokens,
                self.total_usage.completion_tokens + response.usage.completion_tokens,
            )
        return response

    def list_models(self) -> tuple[str, ...]:
        raw = self._send(self.config.models_endpoint(), None, retries=0)
        try:
            data = json.loads(raw.decode("utf-8"))
            return tuple(sorted(str(item["id"]) for item in data["data"]))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProviderError("provider returned an invalid model list") from exc

    def test_connection(self) -> str:
        """Return a short status message; raises ProviderError on failure."""
        try:
            models = self.list_models()
        except ProviderError as exc:
            if exc.status not in {404, 405}:
                raise
            models = ()
        if models and self.config.model not in models:
            return f"Connected, but model {self.config.model!r} is not listed ({len(models)} models available)"
        return f"Connected to {self.config.base_url} (model {self.config.model})"

    # ----------------------------------------------------------------- transport
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _send(self, url: str, data: bytes | None, *, retries: int | None = None) -> bytes:
        attempts = (self.config.max_retries if retries is None else retries) + 1
        last_error: ProviderError | None = None
        for attempt in range(attempts):
            if self.cancel_event.is_set():
                raise ProviderCancelled()
            http_request = urllib_request.Request(
                url, data=data, headers=self._headers(), method="POST" if data is not None else "GET"
            )
            retry_after: float | None = None
            try:
                with urllib_request.urlopen(http_request, timeout=self.config.timeout) as response:
                    return response.read()
            except HTTPError as exc:
                last_error = self._http_error(exc)
                retry_after = self._retry_after(exc)
            except (URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(reason, (socket.timeout, TimeoutError)) or isinstance(exc, (socket.timeout, TimeoutError)):
                    message = f"provider request timed out after {self.config.timeout:g}s"
                else:
                    message = f"provider connection failed: {self._safe(str(reason))}"
                last_error = ProviderError(message, retryable=True)
            if not last_error.retryable or attempt == attempts - 1:
                break
            delay = retry_after if retry_after is not None else self.config.retry_backoff * (2 ** attempt)
            self._wait(min(delay, _MAX_RETRY_AFTER))
        assert last_error is not None
        if attempts > 1 and last_error.retryable:
            raise ProviderError(
                f"{last_error} (after {attempts} attempts)", status=last_error.status, retryable=True
            )
        raise last_error

    def _wait(self, seconds: float) -> None:
        if self._sleep is time.sleep:
            cancelled = self.cancel_event.wait(seconds)
        else:
            self._sleep(seconds)
            cancelled = self.cancel_event.is_set()
        if cancelled:
            raise ProviderCancelled()

    def _http_error(self, exc: HTTPError) -> ProviderError:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except OSError:
            detail = ""
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                detail = str(parsed["error"].get("message") or detail)
        except (json.JSONDecodeError, ValueError):
            pass
        detail = self._safe(detail)[:_MAX_ERROR_DETAIL]
        hint = {
            401: " (check the API key)",
            403: " (access denied for this key or model)",
            404: " (check the base URL and model name)",
            429: " (rate limited)",
        }.get(exc.code, "")
        return ProviderError(
            f"provider HTTP {exc.code}{hint}: {detail}".rstrip(": "),
            status=exc.code,
            retryable=exc.code in _RETRYABLE_STATUS,
        )

    @staticmethod
    def _retry_after(exc: HTTPError) -> float | None:
        value = exc.headers.get("Retry-After") if exc.headers else None
        try:
            return max(0.0, float(value)) if value is not None else None
        except ValueError:
            return None

    def _safe(self, text: str) -> str:
        extra = (self.config.api_key,) if self.config.api_key else ()
        return redact_secrets(text, extra)[0]

    # ------------------------------------------------------------------ payload
    def _message(self, message: AgentMessage) -> dict[str, object]:
        content = message.content
        if self.config.redact_secrets:
            content, replaced = redact_secrets(content)
            self.redactions += replaced
        result: dict[str, object] = {"role": message.role, "content": content}
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
            raise ProviderError("provider returned an invalid Chat Completions response") from exc
        if not isinstance(message, dict):
            raise ProviderError("provider returned an invalid Chat Completions response")

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ProviderError("provider response content must be a string")

        calls: list[ToolCall] = []
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ProviderError("provider response tool_calls must be a list")

        for raw_call in raw_calls:
            try:
                function = raw_call["function"]
                call_id = raw_call["id"]
                name = function["name"]
                arguments = function.get("arguments", "{}")
                parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                raise ProviderError("provider returned an invalid tool call") from exc
            if not isinstance(call_id, str) or not isinstance(name, str):
                raise ProviderError("provider tool call id and name must be strings")
            if not isinstance(parsed_arguments, dict):
                raise ProviderError("provider tool call arguments must be a JSON object")
            calls.append(ToolCall(call_id, name, parsed_arguments))

        usage = None
        raw_usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(raw_usage, dict):
            try:
                usage = TokenUsage(
                    int(raw_usage.get("prompt_tokens") or 0), int(raw_usage.get("completion_tokens") or 0)
                )
            except (TypeError, ValueError):
                usage = None
        return ProviderResponse(content, tuple(calls), usage)
