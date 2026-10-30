from __future__ import annotations

import json

from vibe_code.context.models import ContextPack
from vibe_code.agent.service import AgentRequest, AgentService
from vibe_code.providers.base import AIProvider


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SELECTION_BYTES = 256 * 1024
CONTEXT_LINES = 35


def propose_selection_edit(
    provider: AIProvider,
    relative_path: str,
    source: str,
    selection_start: int,
    selection_end: int,
    instruction: str,
) -> str:
    """Ask the provider for a replacement of exactly one selected range.

    The provider returns JSON, not a patch or a tool call. This function never
    writes to disk; callers must review and explicitly apply the returned text.
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Edit instruction must not be empty")
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("A workspace-relative file path is required")
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError("Source file exceeds the 2 MiB editor limit")
    if selection_start < 0 or selection_end <= selection_start or selection_end > len(source):
        raise ValueError("Select a non-empty range of source code first")
    selected = source[selection_start:selection_end]
    if len(selected.encode("utf-8")) > MAX_SELECTION_BYTES:
        raise ValueError("Selected code exceeds the 256 KiB AI edit limit")

    start_line = source.count("\n", 0, selection_start)
    end_line = source.count("\n", 0, selection_end)
    lines = source.splitlines()
    context_start = max(0, start_line - CONTEXT_LINES)
    context_end = min(len(lines), end_line + CONTEXT_LINES + 1)
    before_context = "\n".join(lines[context_start:start_line])
    after_context = "\n".join(lines[end_line + 1:context_end])

    prompt = (
        "Edit only the selected code. Return exactly one JSON object with a single "
        'string property named "replacement". Do not use Markdown fences, explanations, '
        "or additional properties. The replacement must contain only the new text for "
        "the selected range; surrounding code is context and must not be repeated.\n\n"
        f"File: {relative_path}\n"
        f"Instruction:\n{instruction.strip()}\n\n"
        f"Context before selection:\n{before_context}\n\n"
        f"Selected code (replace this exact range):\n{selected}\n\n"
        f"Context after selection:\n{after_context}"
    )
    response = AgentService.complete(
        provider,
        AgentRequest(prompt, ContextPack((), estimated_tokens=0)),
    )
    if len(response.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("AI response exceeds the 2 MiB safety limit")
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError("AI response was not valid JSON; no changes were applied") from exc
    if not isinstance(payload, dict) or set(payload) != {"replacement"}:
        raise ValueError('AI response must contain only the "replacement" string property')
    replacement = payload["replacement"]
    if not isinstance(replacement, str):
        raise ValueError('AI response "replacement" must be a string')
    updated = source[:selection_start] + replacement + source[selection_end:]
    if len(updated.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Edited source exceeds the 2 MiB editor limit")
    return updated
