from pathlib import Path

from vibe_code.index import ProjectIndexer


def test_python_index_extracts_symbols_and_imports(tmp_path: Path) -> None:
    source = (
        "import pathlib\n"
        "from collections import deque\n\n"
        "class App:\n"
        "    def run(self):\n"
        "        pass\n"
    )
    path = tmp_path / "app.py"
    path.write_text(source, encoding="utf-8")

    result = ProjectIndexer().build(tmp_path)

    assert len(result) == 1
    assert result[0].language == "python"
    assert [(s.name, s.kind) for s in result[0].symbols] == [
        ("App", "class"),
        ("run", "function"),
    ]
    assert result[0].imports == ("collections", "pathlib")


def test_indexer_skips_ignored_directories(tmp_path: Path) -> None:
    ignored = tmp_path / ".venv"
    ignored.mkdir()
    (ignored / "hidden.py").write_text("def hidden(): pass", encoding="utf-8")
    (tmp_path / "main.py").write_text("def main(): pass", encoding="utf-8")

    result = ProjectIndexer().build(tmp_path)

    assert [item.path.name for item in result] == ["main.py"]
