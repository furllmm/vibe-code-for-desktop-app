import json
import threading

import pytest

from vibe_code.agent.autonomy import (
    AutonomousRunner,
    CheckpointStore,
    RunLimits,
    guard_registry,
    parse_plan,
)
from vibe_code.agent.service import AgentLoop
from vibe_code.context.service import ContextService
from vibe_code.providers.base import ProviderResponse, TokenUsage
from vibe_code.runtime.validation import ValidationResult, ValidationStep
from vibe_code.tools.base import ToolResult
from vibe_code.tools.registry import ToolRegistry

PLAN = json.dumps({"tasks": [{"title": "Add feature", "detail": "x"}, {"title": "Write tests"}]})


class Provider:
    def __init__(self, plan=PLAN, reply="done", usage=None):
        self.plan = plan
        self.reply = reply
        self.usage = usage
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return ProviderResponse(self.plan, usage=self.usage)
        return ProviderResponse(self.reply, usage=self.usage)


def ok():
    return ValidationResult(True, (ValidationStep("Tests", True, "2 passed"),), True)


def bad(text="AssertionError"):
    return ValidationResult(False, (ValidationStep("Tests", False, text),), False)


def runner(tmp_path, provider, validate=None, **kwargs):
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return AutonomousRunner(
        AgentLoop(provider, ToolRegistry()), ContextService(), tmp_path, validate=validate, **kwargs
    )


def test_full_do_plans_and_completes_with_validation(tmp_path):
    progress = []
    result = runner(tmp_path, Provider(), ok, on_progress=progress.append).start("full_do", "")

    assert result.status == "completed"
    assert [t.status for t in result.tasks] == ["passed", "passed"]
    assert result.summary().startswith("full_do run completed: 2 passed")
    assert progress and progress[-1].status == "completed"
    saved = CheckpointStore(tmp_path).load(result.run_id)
    assert saved.status == "completed" and saved.iterations == 2


def test_without_validation_tasks_are_untested_not_passed(tmp_path):
    result = runner(tmp_path, Provider()).start("continue", "finish login")
    assert [t.status for t in result.tasks] == ["untested", "untested"]
    assert result.status == "completed"


def test_failed_validation_is_retried_with_diagnostics_then_fails(tmp_path):
    outcomes = iter([bad("E1"), ok(), bad("E2"), bad("E3"), bad("E4")])
    provider = Provider(reply="attempt")
    result = runner(tmp_path, provider, lambda: next(outcomes), limits=RunLimits(max_retries_per_task=2, loop_window=5)).start("full_do", "")

    assert [t.status for t in result.tasks] == ["passed", "failed"]
    assert result.tasks[1].attempts == 3
    assert result.status == "failed"
    retry_prompt = provider.requests[2].messages[-1].content
    assert "Previous attempt failed validation" in retry_prompt and "E1" in retry_prompt


def test_loop_detection_stops_identical_failures(tmp_path):
    result = runner(tmp_path, Provider(), lambda: bad("same"),
                    limits=RunLimits(max_retries_per_task=10, loop_window=3)).start("full_do", "")
    assert result.status == "interrupted"
    assert "loop detected" in result.stop_reason
    assert result.tasks[0].attempts == 3


def test_iteration_and_token_budgets(tmp_path):
    result = runner(tmp_path, Provider(), lambda: bad(), limits=RunLimits(max_iterations=1)).start("full_do", "")
    assert result.status == "interrupted" and "iteration limit" in result.stop_reason

    heavy = Provider(usage=TokenUsage(600, 0))
    result = runner(tmp_path, heavy, ok, limits=RunLimits(max_tokens=1000)).start("full_do", "")
    assert "token budget" in result.stop_reason


def test_time_budget(tmp_path):
    ticks = iter(range(0, 10_000, 100))
    result = runner(tmp_path, Provider(), ok, limits=RunLimits(max_seconds=150),
                    clock=lambda: float(next(ticks))).start("full_do", "")
    assert "time budget" in result.stop_reason


def test_cancel_then_resume_finishes_remaining_tasks(tmp_path):
    event = threading.Event()
    calls = []

    def validate():
        calls.append(1)
        event.set()
        return ok()

    first = runner(tmp_path, Provider(), validate, cancel_event=event).start("full_do", "", run_id="run1")
    assert first.status == "stopped" and first.stop_reason == "cancelled by user"
    assert [t.status for t in first.tasks] == ["passed", "pending"]

    resumed = runner(tmp_path, Provider(reply="ok"), ok).resume("run1")
    assert resumed.status == "completed"
    assert [t.status for t in resumed.tasks] == ["passed", "passed"]


def test_interrupted_running_task_is_reset_on_resume(tmp_path):
    store = CheckpointStore(tmp_path)
    first = runner(tmp_path, Provider(), ok, limits=RunLimits(max_iterations=1)).start("full_do", "", run_id="r2")
    first.tasks[1].status = "running"
    store.save(first)
    resumed = runner(tmp_path, Provider(), ok).resume("r2")
    assert resumed.tasks[1].status == "passed"
    assert any("resumed" in line for line in resumed.log)
    assert store.latest_resumable() is None


def test_corrupted_checkpoint_is_rejected_and_skipped(tmp_path):
    store = CheckpointStore(tmp_path)
    store.directory.mkdir(parents=True)
    (store.directory / "bad.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrupted"):
        store.load("bad")
    assert store.latest_resumable() is None
    with pytest.raises(ValueError):
        store.path_for("../escape")


def test_plan_parsing_is_tolerant_of_malformed_replies():
    assert parse_plan('```json\n{"tasks": [{"title": "A"}, {"bad": 1}, {"title": ""}]}\n```') == [("A", "")]
    assert parse_plan("Plan:\n1. First\n- Second\nprose") == [("First", ""), ("Second", "")]
    assert parse_plan("no plan here") == []
    assert parse_plan('{"tasks": "nope"}') == []


def test_unparseable_plan_falls_back_to_single_goal_task(tmp_path):
    result = runner(tmp_path, Provider(plan="I cannot comply"), ok).start("continue", "fix the bug")
    assert [t.title for t in result.tasks] == ["fix the bug"]


def test_destructive_tools_require_approval():
    class Rollback:
        name = "rollback_changes"
        description = "Rollback."
        parameters = {}

        def execute(self, arguments):
            return ToolResult(True, "rolled back")

    class Read:
        name = "read_file"
        description = "Read."
        parameters = {}

        def execute(self, arguments):
            return ToolResult(True, "content")

    asked = []
    guarded = guard_registry(ToolRegistry((Rollback(), Read())), lambda name, args: asked.append(name) or False)
    assert guarded.get("rollback_changes").execute({"change_id": "x"}).ok is False
    assert guarded.get("read_file").execute({}).ok is True
    assert asked == ["rollback_changes"]
