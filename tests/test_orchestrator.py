from pathlib import Path

from vibe_code.agent.orchestrator import AgentOrchestrator
from vibe_code.agent.service import AgentRunResult
from vibe_code.changes import ChangeManager
from vibe_code.context.models import ContextPack
from vibe_code.runtime.process import ProcessResult
from vibe_code.tools.filesystem import WorkspaceFS


class FakeContext:
    def build(self, request):
        return ContextPack((), 0)


class FakeAgent:
    def __init__(self):
        self.prompts = []

    def run(self, request):
        self.prompts.append(request.prompt)
        return AgentRunResult("done", (), (), 1)


class FakePreview:
    def __init__(self, results, logs):
        self.results = list(results)
        self.logs = list(logs)

    def stop(self):
        return None

    def build(self):
        return None

    def start(self):
        return None

    def poll(self):
        return self.results.pop(0) if self.results else None

    def read_logs(self):
        return self.logs.pop(0) if self.logs else ""


def test_orchestrator_reports_preview_failure(tmp_path: Path):
    changes = ChangeManager(WorkspaceFS(tmp_path))
    agent = FakeAgent()
    preview = FakePreview([ProcessResult(1, True)], ["Traceback: broken"])
    orchestrator = AgentOrchestrator(
        agent, FakeContext(), changes, preview, tmp_path, startup_timeout=0.1
    )

    result = orchestrator.run("add a button")

    assert result.failure is not None
    assert result.failure.returncode == 1
    assert "broken" in result.failure.logs


def test_orchestrator_repairs_with_bounded_cycles(tmp_path: Path):
    changes = ChangeManager(WorkspaceFS(tmp_path))
    agent = FakeAgent()
    preview = FakePreview(
        [ProcessResult(1, True), ProcessResult(0, False)],
        ["bad preview", "ok"],
    )
    orchestrator = AgentOrchestrator(
        agent, FakeContext(), changes, preview, tmp_path, max_repair_cycles=2, startup_timeout=0.1
    )

    first = orchestrator.run("add a button")
    repaired = orchestrator.repair(first.failure)

    assert repaired.success
    assert len(repaired.attempts) == 1
    assert "bad preview" in agent.prompts[1]
    assert "Exit code: 1" in agent.prompts[1]


def test_orchestrator_stops_after_repair_limit(tmp_path: Path):
    changes = ChangeManager(WorkspaceFS(tmp_path))
    agent = FakeAgent()
    preview = FakePreview(
        [ProcessResult(1, True), ProcessResult(2, True)],
        ["bad1", "bad2"],
    )
    orchestrator = AgentOrchestrator(
        agent, FakeContext(), changes, preview, tmp_path, max_repair_cycles=2, startup_timeout=0.1
    )

    first = orchestrator.run("fix it")
    repaired = orchestrator.repair(first.failure)

    assert not repaired.success
    assert repaired.stopped_by_limit
    assert len(repaired.attempts) == 2
