from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TaskState:
    original_prompt: str
    status: str
    last_result: str = ""
    updated_at: str = ""

    def continuation_prompt(self) -> str:
        result = self.last_result.strip() or "No final agent report was saved."
        return (
            "Continue the previous task from its saved checkpoint.\n\n"
            "Original user request:\n"
            + self.original_prompt
            + "\n\nLast saved agent report (treat as a claim, not proof):\n"
            + result[-6000:]
            + "\n\nFirst inspect the current workspace and change history. Verify what is "
            "already implemented, identify remaining acceptance criteria, and continue only "
            "the unfinished work. Do not blindly repeat completed edits. Preserve unrelated "
            "user changes. Run available validation and report what was actually verified."
        )


class TaskStateStore:
    """Atomically persist a small, non-secret resume checkpoint in the workspace."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.path = self.workspace / ".vibe-code" / "task_state.json"

    def load(self) -> TaskState | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read saved task state: {exc}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("Saved task state has an invalid format")
        prompt = raw.get("original_prompt")
        status = raw.get("status")
        result = raw.get("last_result", "")
        updated = raw.get("updated_at", "")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError("Saved task state has no valid original prompt")
        if not isinstance(status, str) or not isinstance(result, str) or not isinstance(updated, str):
            raise RuntimeError("Saved task state has invalid fields")
        return TaskState(prompt, status, result, updated)

    def save(self, state: TaskState) -> None:
        if not state.original_prompt.strip():
            raise ValueError("original_prompt must not be empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(
            TaskState(
                original_prompt=state.original_prompt,
                status=state.status,
                last_result=state.last_result[-12000:],
                updated_at=state.updated_at or datetime.now(timezone.utc).isoformat(),
            )
        )
        fd, temp_name = tempfile.mkstemp(prefix=".task-state-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
