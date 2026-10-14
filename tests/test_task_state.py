from __future__ import annotations

import json

import pytest

from vibe_code.agent.task_state import TaskState, TaskStateStore


def test_task_state_round_trip_and_continuation_prompt(tmp_path):
    store = TaskStateStore(tmp_path)
    store.save(TaskState("Add settings", "interrupted", "Settings page partially implemented"))
    loaded = store.load()

    assert loaded is not None
    assert loaded.original_prompt == "Add settings"
    assert loaded.status == "interrupted"
    prompt = loaded.continuation_prompt()
    assert "inspect the current workspace" in prompt
    assert "Do not blindly repeat completed edits" in prompt


def test_task_state_is_atomically_written_as_json(tmp_path):
    store = TaskStateStore(tmp_path)
    store.save(TaskState("Improve UI", "running"))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["original_prompt"] == "Improve UI"
    assert payload["status"] == "running"
    assert not list(store.path.parent.glob(".task-state-*"))


def test_corrupt_task_state_reports_clear_error(tmp_path):
    store = TaskStateStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Could not read saved task state"):
        store.load()
