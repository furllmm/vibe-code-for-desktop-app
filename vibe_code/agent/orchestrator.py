from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path

from ..changes import ChangeManager
from ..context.models import ContextRequest
from ..context.service import ContextService
from ..runtime.preview import PreviewEngine
from .service import AgentLoop, AgentRequest, AgentRunResult


@dataclass(frozen=True)
class PreviewFailure:
    cycle: int
    logs: str
    returncode: int
    change_ids: tuple[str, ...]


@dataclass(frozen=True)
class OrchestrationResult:
    agent: AgentRunResult
    change_ids: tuple[str, ...]
    failure: PreviewFailure | None = None


@dataclass(frozen=True)
class RepairResult:
    attempts: tuple[OrchestrationResult, ...]
    success: bool
    stopped_by_limit: bool


class AgentOrchestrator:
    """Own the agent -> preview -> diagnostics loop outside the Qt UI."""

    def __init__(
        self,
        agent: AgentLoop,
        context: ContextService,
        changes: ChangeManager,
        preview: PreviewEngine,
        workspace: Path,
        *,
        max_repair_cycles: int = 3,
        startup_timeout: float = 2.0,
    ) -> None:
        if max_repair_cycles < 1:
            raise ValueError("max_repair_cycles must be at least 1")
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be greater than zero")
        self.agent = agent
        self.context = context
        self.changes = changes
        self.preview = preview
        self.workspace = workspace.resolve()
        self.max_repair_cycles = max_repair_cycles
        self.startup_timeout = startup_timeout

    def run(self, prompt: str, *, token_budget: int = 12000) -> OrchestrationResult:
        return self._run_once(prompt.strip(), 1, token_budget)

    def repair(
        self,
        failure: PreviewFailure,
        *,
        token_budget: int = 12000,
    ) -> RepairResult:
        attempts: list[OrchestrationResult] = []
        current = self._repair_prompt(failure)

        for cycle in range(1, self.max_repair_cycles + 1):
            result = self._run_once(current, cycle, token_budget)
            attempts.append(result)
            if result.failure is None:
                return RepairResult(tuple(attempts), True, False)
            current = self._repair_prompt(result.failure)

        return RepairResult(tuple(attempts), False, True)

    def _run_once(
        self,
        prompt: str,
        cycle: int,
        token_budget: int,
    ) -> OrchestrationResult:
        if not prompt:
            raise ValueError("prompt must not be empty")

        before = {change.id for change in self.changes.list_changes()}
        context = self.context.build(
            ContextRequest(prompt, self.workspace, token_budget=token_budget)
        )
        agent_result = self.agent.run(AgentRequest(prompt, context))
        after = self.changes.list_changes()
        change_ids = tuple(change.id for change in after if change.id not in before)

        self.preview.stop()
        self.preview.build()
        self.preview.start()

        result = self._wait_for_preview()
        logs = self.preview.read_logs()
        if result is None:
            return OrchestrationResult(agent_result, change_ids)

        if not result.crashed:
            return OrchestrationResult(agent_result, change_ids)

        failure = PreviewFailure(
            cycle=cycle,
            logs=logs,
            returncode=result.returncode,
            change_ids=change_ids,
        )
        return OrchestrationResult(agent_result, change_ids, failure)

    def _repair_prompt(self, failure: PreviewFailure) -> str:
        sections = [
            "Repair the current desktop app after the preview crashed.",
            "Inspect the current workspace and make the smallest maintainable fix.",
            "Do not merely explain the error; edit the relevant files.",
            "Previous preview diagnostics:",
            failure.logs.strip() or "<no captured output>",
            f"Exit code: {failure.returncode}",
        ]
        diffs: list[str] = []
        for change_id in failure.change_ids:
            try:
                diff = self.changes.diff(change_id)
            except (OSError, KeyError, RuntimeError):
                continue
            if diff and diff != "(no textual diff)":
                diffs.append(f"Change {change_id[:12]}:\n{diff}")
        if diffs:
            sections.append("Changes from the failed repair attempt:\n" + "\n\n".join(diffs))
        return "\n".join(sections)

    def _wait_for_preview(self):
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            result = self.preview.poll()
            if result is not None:
                return result
            time.sleep(0.01)
        return None
