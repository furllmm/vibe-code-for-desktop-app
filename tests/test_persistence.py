"""Workspace state written by earlier/later app versions must survive an upgrade."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibe_code.agent.autonomy import CheckpointStore, PlanTask, RunCheckpoint
from vibe_code.agent.task_state import TaskState, TaskStateStore
from vibe_code.app import MainWindow, run
from vibe_code.context.settings import ContextSettings
from vibe_code.index.indexer import CACHE_VERSION, ProjectIndexer
from vibe_code.workspace import Workspace

_APP = QApplication.instance() or QApplication([])


def _seed(root):
    (root / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    state = root / ".vibe-code"
    (state / "index").mkdir(parents=True)
    (state / "context.json").write_text(
        json.dumps({"token_budget": 5000, "exclude": ["private/**"], "future_option": True}),
        encoding="utf-8",
    )
    (state / "rules.md").write_text("Use type hints.\n", encoding="utf-8")
    (state / "index" / "index.json").write_text(json.dumps({"version": 1, "files": {}}), encoding="utf-8")
    TaskStateStore(root).save(TaskState("Build a todo app", "completed", "done", "2026-01-01"))
    store = CheckpointStore(root)
    store.save(RunCheckpoint("old-run", "full_do", "Finish it", [PlanTask("t1", "Write tests")], status="stopped"))
    path = store.path_for("old-run")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["field_from_newer_version"] = 1
    raw["tasks"][0]["priority"] = "high"
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_workspace_state_survives_app_restart_and_format_drift(tmp_path):
    _seed(tmp_path)
    preserved = {
        name: (tmp_path / ".vibe-code" / name).read_bytes()
        for name in ("context.json", "rules.md", "task_state.json")
    }

    window = MainWindow()
    try:
        window.workspace = Workspace(tmp_path)
        window._set_editor_workspace(window.workspace)
        window.load_workspace(tmp_path)
        assert window.runs_panel.workspace == tmp_path.resolve()
    finally:
        window.close()
        window.deleteLater()

    for name, content in preserved.items():
        assert (tmp_path / ".vibe-code" / name).read_bytes() == content

    settings = ContextSettings.load(tmp_path)
    assert settings.token_budget == 5000
    assert settings.exclude == ("private/**",)
    assert TaskStateStore(tmp_path).load().original_prompt == "Build a todo app"

    checkpoint = CheckpointStore(tmp_path).load("old-run")
    assert checkpoint.status == "stopped"
    assert checkpoint.tasks[0].title == "Write tests"
    assert CheckpointStore(tmp_path).latest_resumable().run_id == "old-run"

    index = ProjectIndexer().build_index(tmp_path, history=False)
    assert "main.py" in index.files
    cache = json.loads((tmp_path / ".vibe-code" / "index" / "index.json").read_text(encoding="utf-8"))
    assert cache["version"] == CACHE_VERSION


def test_cli_version_and_smoke_test(capsys):
    assert run(["vibe-code", "--version"]) == 0
    assert capsys.readouterr().out.startswith("vibe-code ")
    assert run(["vibe-code", "--smoke-test"]) == 0
