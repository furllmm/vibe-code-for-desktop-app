from pathlib import Path

import pytest

from vibe_code.context.models import ContextRequest
from vibe_code.context.service import ContextService
from vibe_code.workspace import Workspace


def test_context_prefers_relevant_file(tmp_path: Path) -> None:
    (tmp_path / "login.py").write_text("def login(): pass\n", encoding="utf-8")
    (tmp_path / "settings.py").write_text("theme = 'dark'\n", encoding="utf-8")
    pack = ContextService().build(ContextRequest("fix login", tmp_path, 1000))
    assert pack.items
    assert pack.items[0].path.name == "login.py"


def test_context_uses_symbol_relevance(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text(
        "def authenticate_user():\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "utils.py").write_text(
        "def format_name(value):\n    return value\n", encoding="utf-8"
    )
    pack = ContextService().build(
        ContextRequest("fix authenticate_user", tmp_path, 1000)
    )
    assert pack.items
    assert pack.items[0].path.name == "auth.py"
    assert "symbol:authenticate_user" in pack.items[0].reason


def test_context_respects_budget(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a" * 4000, encoding="utf-8")
    (tmp_path / "b.py").write_text("b" * 4000, encoding="utf-8")
    pack = ContextService().build(ContextRequest("a b", tmp_path, 1000))
    assert pack.estimated_tokens <= 1000


def test_workspace_rejects_escape(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(ValueError):
        workspace.resolve("../outside")


def test_workspace_resolves_relative_paths(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    target = workspace.resolve("src/main.py")
    assert target == (tmp_path / "src/main.py").resolve()


def test_context_selects_matching_symbol_range(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "def unrelated():\n    return 'x' * 1000\n\n"
        "def target_function():\n    return 42\n\n"
        "def another():\n    return 'y' * 1000\n",
        encoding="utf-8",
    )

    pack = ContextService().build(
        ContextRequest("fix target_function", tmp_path, 1000)
    )

    item = pack.items[0]
    assert "def target_function" in (item.content or "")
    assert "def unrelated" not in (item.content or "")
    assert item.start_line == 4
    assert item.end_line == 5


def test_context_prioritizes_uncommitted_git_file(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "changed.py").write_text("def changed(): pass\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("def other(): pass\n", encoding="utf-8")

    pack = ContextService().build(ContextRequest("unrelated", tmp_path, 1000))

    assert pack.items
    assert pack.items[0].path.name == "changed.py"
    assert "recent git change" in pack.items[0].reason
