from pathlib import Path
from vibe_code.context.models import ContextRequest
from vibe_code.context.service import ContextService

def test_context_prefers_relevant_file(tmp_path: Path) -> None:
    (tmp_path / "login.py").write_text("def login(): pass\n", encoding="utf-8")
    (tmp_path / "settings.py").write_text("theme = 'dark'\n", encoding="utf-8")
    pack = ContextService().build(ContextRequest("fix login", tmp_path, 1000))
    assert pack.items
    assert pack.items[0].path.name == "login.py"

def test_context_respects_budget(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a" * 4000, encoding="utf-8")
    (tmp_path / "b.py").write_text("b" * 4000, encoding="utf-8")
    pack = ContextService().build(ContextRequest("a b", tmp_path, 1000))
    assert pack.estimated_tokens <= 1000
