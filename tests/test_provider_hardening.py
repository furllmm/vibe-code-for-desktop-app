import io
import json
import threading
from urllib.error import HTTPError, URLError

import pytest

from vibe_code.providers import (
    AgentMessage,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderCancelled,
    ProviderError,
    ProviderRequest,
)
from vibe_code.security import is_sensitive_path, redact_secrets

URLOPEN = "vibe_code.providers.openai_compatible.urllib_request.urlopen"
KEY = "sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def ok(content="done", usage=None):
    body = {"choices": [{"message": {"content": content}}]}
    if usage:
        body["usage"] = usage
    return Response(body)


def http_error(code, body="", headers=None):
    return HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body.encode()))


def provider(**kwargs):
    sleeps = []
    instance = OpenAICompatibleProvider(
        OpenAICompatibleConfig("http://localhost/v1", "m", KEY, **kwargs), sleep=sleeps.append
    )
    return instance, sleeps


def request(text="hi"):
    return ProviderRequest([AgentMessage("user", text)])


def test_retries_rate_limit_honouring_retry_after_and_tracks_usage(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise http_error(429, "slow down", {"Retry-After": "3"})
        if len(calls) == 2:
            raise URLError("connection reset")
        return ok(usage={"prompt_tokens": 10, "completion_tokens": 5})

    monkeypatch.setattr(URLOPEN, fake)
    instance, sleeps = provider(max_retries=2, retry_backoff=0.5)

    response = instance.complete(request())

    assert response.content == "done"
    assert sleeps == [3.0, 1.0]
    assert response.usage.total_tokens == 15
    assert instance.total_usage.prompt_tokens == 10


def test_non_retryable_errors_fail_fast_with_hint_and_no_key(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        raise http_error(401, json.dumps({"error": {"message": f"bad key {KEY}"}}))

    monkeypatch.setattr(URLOPEN, fake)
    instance, _ = provider()

    with pytest.raises(ProviderError) as info:
        instance.complete(request())

    assert len(calls) == 1
    assert info.value.status == 401
    assert "check the API key" in str(info.value)
    assert KEY not in str(info.value)
    assert KEY not in repr(instance.config)


def test_exhausted_retries_report_attempts(monkeypatch):
    monkeypatch.setattr(URLOPEN, lambda req, timeout: (_ for _ in ()).throw(http_error(503)))
    instance, sleeps = provider(max_retries=2)

    with pytest.raises(ProviderError, match="after 3 attempts"):
        instance.complete(request())
    assert sleeps == [1.0, 2.0]


def test_timeout_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(URLOPEN, lambda req, timeout: (_ for _ in ()).throw(TimeoutError()))
    instance, _ = provider(max_retries=0, timeout=5)

    with pytest.raises(ProviderError, match="timed out after 5s"):
        instance.complete(request())


def test_cancellation_stops_before_and_between_attempts(monkeypatch):
    monkeypatch.setattr(URLOPEN, lambda req, timeout: (_ for _ in ()).throw(http_error(500)))
    event = threading.Event()
    instance = OpenAICompatibleProvider(
        OpenAICompatibleConfig("http://localhost/v1", "m"), sleep=lambda s: event.set(), cancel_event=event
    )
    with pytest.raises(ProviderCancelled):
        instance.complete(request())

    instance.cancel()
    with pytest.raises(ProviderCancelled):
        instance.complete(request())


def test_secrets_are_redacted_from_outgoing_messages(monkeypatch):
    captured = {}

    def fake(req, timeout):
        captured["payload"] = json.loads(req.data)
        return ok()

    monkeypatch.setattr(URLOPEN, fake)
    instance, _ = provider()
    instance.complete(request('config:\nAWS = "AKIAABCDEFGHIJKLMNOP"\npassword = "hunter2hunter2"\nok = 1'))

    sent = captured["payload"]["messages"][0]["content"]
    assert "AKIA" not in sent and "hunter2" not in sent
    assert "ok = 1" in sent
    assert instance.redactions == 2


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"choices": []}', b'{"choices": [{"message": "x"}]}',
                                  b'{"choices": [{"message": {"content": 5}}]}',
                                  b'{"choices": [{"message": {"tool_calls": [{"id": 1}]}}]}'])
def test_malformed_responses_raise_provider_error(monkeypatch, body):
    class Raw(Response):
        def read(self):
            return body

    monkeypatch.setattr(URLOPEN, lambda req, timeout: Raw(None))
    instance, _ = provider()
    with pytest.raises(ProviderError):
        instance.complete(request())


def test_connection_test_and_model_listing(monkeypatch):
    def fake(req, timeout):
        assert req.get_method() == "GET"
        return Response({"data": [{"id": "m"}, {"id": "other"}]})

    monkeypatch.setattr(URLOPEN, fake)
    instance, _ = provider()
    assert instance.list_models() == ("m", "other")
    assert "Connected" in instance.test_connection()


def test_redaction_keeps_ordinary_code():
    code = "def token_count(self):\n    return self.max_tokens\nmax_tokens = 4096\napi_key = os.environ['KEY']\n"
    assert redact_secrets(code) == (code, 0)
    text, count = redact_secrets("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----")
    assert text == "[REDACTED]" and count == 1


@pytest.mark.parametrize("path,expected", [
    (".env.local", True), ("config/.ssh/id_rsa", True), ("certs/server.pem", True),
    ("app/api_keys.py", True), ("src/main.py", False), ("docs/tokens.md", False),
])
def test_sensitive_paths(path, expected):
    from pathlib import PurePosixPath
    assert is_sensitive_path(PurePosixPath(path)) is expected
