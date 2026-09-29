from pathlib import Path

from vibe_code.agent.repair import RepairLoop
from vibe_code.agent.service import AgentRunResult
from vibe_code.context.models import ContextPack
from vibe_code.runtime.process import ProcessResult


class FakeContext:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def build(self, request):
        self.prompts.append(request.prompt)
        return ContextPack((), 0)


class FakeAgent:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, request):
        self.prompts.append(request.prompt)
        return AgentRunResult("fixed", (), (), 1)


class FakePreview:
    def __init__(self, results: list[ProcessResult | None], logs: list[str]) -> None:
        self.results = list(results)
        self.logs = list(logs)
        self.starts = 0
        self.stops = 0

    def stop(self):
        self.stops += 1

    def build(self):
        return None

    def start(self):
        self.starts += 1

    def poll(self):
        return self.results.pop(0) if self.results else None

    def read_logs(self):
        return self.logs.pop(0) if self.logs else ""


def test_repair_loop_stops_after_success(tmp_path: Path) -> None:
    agent = FakeAgent()
    preview = FakePreview([ProcessResult(0, False)], ["ok"])
    loop = RepairLoop(agent, preview, FakeContext(), tmp_path, startup_timeout=0.1)

    result = loop.run("add a button")

    assert result.success
    assert not result.stopped_by_limit
    assert len(result.cycles) == 1
    assert agent.prompts == ["add a button"]


def test_repair_loop_feeds_crash_diagnostics_into_next_cycle(tmp_path: Path) -> None:
    agent = FakeAgent()
    preview = FakePreview(
        [ProcessResult(1, True), ProcessResult(0, False)],
        ["Traceback: broken widget", "fixed"],
    )
    context = FakeContext()
    loop = RepairLoop(agent, preview, context, tmp_path, max_cycles=2, startup_timeout=0.1)

    result = loop.run("add a button")

    assert result.success
    assert len(result.cycles) == 2
    assert "broken widget" in agent.prompts[1]
    assert "Exit code: 1" in agent.prompts[1]


def test_repair_loop_is_bounded(tmp_path: Path) -> None:
    agent = FakeAgent()
    preview = FakePreview([ProcessResult(2, True), ProcessResult(3, True)], ["bad1", "bad2"])
    loop = RepairLoop(agent, preview, FakeContext(), tmp_path, max_cycles=2, startup_timeout=0.1)

    result = loop.run("fix it")

    assert not result.success
    assert result.stopped_by_limit
    assert len(result.cycles) == 2
