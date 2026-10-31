import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibe_code.agent.autonomy import AutonomousRunner, CheckpointStore, RunCheckpoint, RunLimits
from vibe_code.agent.background import BackgroundTaskManager, DuplicateTaskError
from vibe_code.agent.runs_panel import RunsPanel
from vibe_code.agent.service import AgentLoop
from vibe_code.context.service import ContextService
from vibe_code.providers.base import ProviderResponse
from vibe_code.tools.registry import ToolRegistry

_APP = QApplication.instance() or QApplication([])


def test_duplicate_submission_is_rejected_and_cancel_propagates():
    manager = BackgroundTaskManager()
    started = threading.Event()

    def work(cancel_event, progress):
        started.set()
        cancel_event.wait(5)
        return RunCheckpoint("r", "full_do", "g", [], status="stopped", stop_reason="cancelled by user")

    manager.submit("k", "job", work)
    started.wait(2)
    with pytest.raises(DuplicateTaskError):
        manager.submit("k", "job", work)
    assert manager.cancel("k")
    assert manager.wait("k", 5)
    assert manager.get("k").status == "stopped"
    assert not manager.cancel("k")


def test_worker_exceptions_are_captured():
    manager = BackgroundTaskManager()
    manager.submit("e", "boom", lambda c, p: (_ for _ in ()).throw(ValueError("bad config")))
    manager.wait("e", 5)
    job = manager.get("e")
    assert job.status == "error" and job.error == "bad config"


class Provider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ProviderResponse('{"tasks": [{"title": "Only task"}]}')
        time.sleep(0.05)
        return ProviderResponse("done")


def test_runs_panel_runs_in_background_and_shows_progress(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    manager = BackgroundTaskManager()

    def factory(validate, cancel_event, progress):
        return AutonomousRunner(AgentLoop(Provider(), ToolRegistry()), ContextService(), tmp_path,
                                cancel_event=cancel_event, on_progress=progress)

    panel = RunsPanel(manager, factory)
    panel.set_workspace(tmp_path)
    panel.start_run()
    job = manager.jobs()[0]
    assert manager.wait(job.key, 10)
    panel.refresh()

    assert panel.runs.topLevelItemCount() == 1
    row = panel.runs.topLevelItem(0)
    assert row.text(2) == "completed" and row.text(4) == "1/1"
    row.setSelected(True)
    assert "[untested] t1 Only task" in panel.details.toPlainText()


def test_interrupted_checkpoint_is_shown_as_resumable(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    runner = AutonomousRunner(AgentLoop(Provider(), ToolRegistry()), ContextService(), tmp_path,
                              limits=RunLimits(max_iterations=1))
    checkpoint = runner.start("full_do", "", run_id="old")
    checkpoint.status = "running"
    CheckpointStore(tmp_path).save(checkpoint)

    panel = RunsPanel(BackgroundTaskManager(), lambda *a: None)
    panel.set_workspace(tmp_path)

    assert panel.runs.topLevelItem(0).text(2) == "interrupted"
    assert "can be resumed" in panel.status.text()
