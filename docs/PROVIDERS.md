# Provider configuration

The IDE talks to any **OpenAI Chat Completions–compatible** endpoint (OpenAI, Azure OpenAI
compatible gateways, OpenRouter, LM Studio, Ollama `/v1`, vLLM, llama.cpp server…). The
Responses API is not supported.

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `VIBE_CODE_BASE_URL` | yes | — | Base URL including `/v1`, e.g. `http://localhost:11434/v1` |
| `VIBE_CODE_MODEL` | yes | — | Model name sent in the request |
| `VIBE_CODE_API_KEY` | no | — | Sent as `Authorization: Bearer …`; omit for local servers |
| `VIBE_CODE_TIMEOUT` | no | `60` | Per-request timeout in seconds |

```bash
# Linux / macOS
export VIBE_CODE_BASE_URL="https://api.openai.com/v1"
export VIBE_CODE_MODEL="gpt-4o-mini"
export VIBE_CODE_API_KEY="sk-..."
vibe-code
```

```powershell
# Windows PowerShell
$env:VIBE_CODE_BASE_URL = "http://localhost:11434/v1"
$env:VIBE_CODE_MODEL = "qwen2.5-coder"
vibe-code
```

Use **Test Provider** in the toolbar to verify the endpoint: it calls `/models`, reports
whether the configured model is listed, and treats servers without `/models` (404/405) as
reachable. Authentication and network errors are shown with secrets removed.

## Behaviour

- Retries (default 2) with exponential backoff for timeouts, connection errors and HTTP
  408/409/425/429/5xx; honours `Retry-After`.
- Cancel buttons abort waiting/retrying immediately.
- Token usage from the response is tracked and counted against autonomous-run budgets.
- Malformed responses raise a readable `ProviderError` instead of crashing.
- Outgoing messages are secret-redacted (see [SECURITY.md](SECURITY.md)).
