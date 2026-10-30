from __future__ import annotations

import os

import pytest

from vibe_code.editor.workspace_search import (
    apply_replacement_plan,
    build_replacement_plan,
    search_workspace,
)
from vibe_code.workspace import Workspace


def test_workspace_search_finds_multiple_matches_and_skips_ignored_paths(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("hello world\nhello again\n", encoding="utf-8")
    nested = root / "src"
    nested.mkdir()
    (nested / "module.py").write_text("HELLO there\n", encoding="utf-8")
    ignored = root / ".venv"
    ignored.mkdir()
    (ignored / "package.py").write_text("hello\n", encoding="utf-8")
    (root / "binary.dat").write_bytes(b"\x00hello")

    matches = search_workspace(Workspace(root), "hello")
    assert [(m.path.name, m.line) for m in matches] == [
        ("main.py", 1), ("main.py", 2), ("module.py", 1)
    ]
    assert len(search_workspace(Workspace(root), "hello", case_sensitive=True)) == 2


def test_replacement_plan_is_preview_only_and_apply_changes_all_matches(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    first = root / "one.txt"
    second = root / "two.txt"
    first.write_text("alpha alpha\n", encoding="utf-8")
    second.write_text("ALPHA beta\n", encoding="utf-8")
    workspace = Workspace(root)

    plan = build_replacement_plan(workspace, "alpha", "omega")
    assert plan.match_count == 3
    assert len(plan.files) == 2
    assert first.read_text(encoding="utf-8") == "alpha alpha\n"
    assert second.read_text(encoding="utf-8") == "ALPHA beta\n"

    assert apply_replacement_plan(workspace, plan) == 3
    assert first.read_text(encoding="utf-8") == "omega omega\n"
    assert second.read_text(encoding="utf-8") == "omega beta\n"


def test_stale_replacement_plan_aborts_before_modifying_any_file(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    first = root / "one.txt"
    second = root / "two.txt"
    first.write_text("find me\n", encoding="utf-8")
    second.write_text("find me too\n", encoding="utf-8")
    workspace = Workspace(root)
    plan = build_replacement_plan(workspace, "find", "replace")
    second.write_text("external update\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after preview"):
        apply_replacement_plan(workspace, plan)
    assert first.read_text(encoding="utf-8") == "find me\n"
    assert second.read_text(encoding="utf-8") == "external update\n"


def test_workspace_search_rejects_empty_query(tmp_path):
    with pytest.raises(ValueError, match="must not be empty"):
        search_workspace(Workspace(tmp_path), "")
