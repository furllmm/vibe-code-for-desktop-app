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
