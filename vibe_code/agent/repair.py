from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path

from ..context.models import ContextPack, ContextRequest
from ..context.service import ContextService
from ..runtime.preview import PreviewEngine
from .service import AgentLoop, AgentRequest, AgentRunResult


@dataclass(frozen=True)
class RepairCycle:
    number: int
    agent: AgentRunResult
    logs: str
    crashed: bool
    returncode: int | None


@dataclass(frozen=True)
class RepairRunResult:
    cycles: tuple[RepairCycle, ...]
    success: bool
    stopped_by_limit: bool


class RepairLoop:
    """Bounded agent -> preview -> diagnostics -> repair orchestration."""

    def __init__(
        self,
        agent: AgentLoop,
        preview: PreviewEngine,
        context: ContextService,
        workspace: Path,
        *,
        max_cycles: int = 3,
        startup_timeout: float = 2.0,
    ) -> None:
        if max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be greater than zero")
        self.agent = agent
        self.preview = preview
        self.context = context
        self.workspace = workspace.resolve()
        self.max_cycles = max_cycles
        self.startup_timeout = startup_timeout

    def run(self, prompt: str, *, token_budget: int = 12000) -> RepairRunResult:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        cycles: list[RepairCycle] = []
        current_prompt = prompt.strip()

        for number in range(1, self.max_cycles + 1):
            context_pack: ContextPack = self.context.build(
                ContextRequest(
                    prompt=current_prompt,
                    workspace=self.workspace,
                    token_budget=token_budget,
                )
            )
            agent_result = self.agent.run(AgentRequest(current_prompt, context_pack))

            # The orchestrator owns preview lifecycle so the repair cycle is deterministic.
            self.preview.stop()
            self.preview.build()
            self.preview.start()

            result = self._wait_for_preview()
            logs = self.preview.read_logs()
            if result is None:
                cycle = RepairCycle(number, agent_result, logs, False, None)
                cycles.append(cycle)
                return RepairRunResult(tuple(cycles), True, False)

            cycles.append(
                RepairCycle(
                    number,
                    agent_result,
                    logs,
                    result.crashed,
                    result.returncode,
                )
            )
            if not result.crashed:
                return RepairRunResult(tuple(cycles), True, False)

            current_prompt = (
                "Repair the current desktop app after the previous preview crashed. "
                "Inspect the current workspace and make the smallest maintainable fix. "
                "Do not merely explain the error; edit the relevant files. "
                "Previous preview diagnostics:\n"
                + (logs.strip() or "<no captured output>")
                + f"\nExit code: {result.returncode}"
            )

        return RepairRunResult(tuple(cycles), False, True)

    def _wait_for_preview(self):
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            result = self.preview.poll()
            if result is not None:
                return result
            time.sleep(0.01)
        return None
