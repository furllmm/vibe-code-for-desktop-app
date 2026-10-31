import json
import os
import subprocess
from pathlib import Path

from vibe_code.context.models import ContextRequest
from vibe_code.context.service import ContextService
from vibe_code.index import ProjectIndexer
from vibe_code.index.extractors import extract_c_family, extract_go, extract_rust
from vibe_code.index.indexer import CACHE_RELATIVE


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())
    return path


def test_python_nested_methods_and_local_dependencies(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/models.py", "class User:\n    def save(self):\n        pass\n")
    write(tmp_path, "pkg/service.py", "from .models import User\nimport json\n\ndef create():\n    return User()\n")
    write(tmp_path, "main.py", "from pkg.service import create\n")

    index = ProjectIndexer().build_index(tmp_path, history=False)

    models = index.files["pkg/models.py"]
    assert [(s.name, s.kind, s.parent) for s in models.symbols] == [
        ("User", "class", None), ("save", "method", "User"),
    ]
    assert index.dependencies["pkg/service.py"] == ("pkg/models.py",)
    assert index.dependencies["main.py"] == ("pkg/service.py",)
    assert "pkg/service.py" in index.dependents["pkg/models.py"]
    assert index.related("pkg/service.py") == {"pkg/models.py", "main.py"}
    assert [(r, s.qualified_name) for r, s in index.find_symbols("save")] == [("pkg/models.py", "User.save")]


def test_rust_symbols_and_module_graph(tmp_path):
    write(tmp_path, "Cargo.toml", "[package]\nname='x'\n")
    write(tmp_path, "src/main.rs", "mod net;\nuse crate::net::client::Client;\nfn main() {\n}\n")
    write(tmp_path, "src/net/mod.rs", "pub mod client;\n")
    write(tmp_path, "src/net/client.rs",
          "pub struct Client {}\nimpl Client {\n    pub fn connect(&self) {\n    }\n}\n")

    index = ProjectIndexer().build_index(tmp_path, history=False)

    client = index.files["src/net/client.rs"]
    assert ("connect", "method", "Client") in [(s.name, s.kind, s.parent) for s in client.symbols]
    assert set(index.dependencies["src/main.rs"]) == {"src/net/mod.rs", "src/net/client.rs"}
    assert index.dependencies["src/net/mod.rs"] == ("src/net/client.rs",)


def test_c_family_symbols_and_includes(tmp_path):
    write(tmp_path, "include/util.h", "#define LIMIT 4\nint add(int a, int b);\n")
    write(tmp_path, "src/main.cpp",
          '#include "util.h"\n#include <vector>\nnamespace app {\nclass Engine {\npublic:\n'
          "    void start() {\n    }\n};\n}\nint main() {\n    return 0;\n}\n")

    index = ProjectIndexer().build_index(tmp_path, history=False)

    symbols = [(s.name, s.kind, s.parent) for s in index.files["src/main.cpp"].symbols]
    assert ("Engine", "class", "app") in symbols
    assert ("start", "method", "Engine") in symbols
    assert ("main", "function", None) in symbols
    assert index.dependencies["src/main.cpp"] == ("include/util.h",)
    assert ("LIMIT", "macro", None) in [(s.name, s.kind, s.parent) for s in index.files["include/util.h"].symbols]


def test_extractors_ignore_comments_and_strings():
    symbols, imports = extract_rust('// fn fake() {}\n/* struct Hidden {} */\nfn real() {\n    let s = "}";\n}\n')
    assert [(s[0], s[3]) for s in symbols] == [("real", 5)]
    assert imports == []
    c_symbols, c_imports = extract_c_family("// int fake() {}\nint proto(int);\nif (x) {\n}\n")
    assert c_symbols == [] and c_imports == []
    go_symbols, go_imports = extract_go(
        'package main\nimport (\n    "fmt"\n    m "example.com/x/model"\n)\n'
        "type Server struct {\n}\nfunc (s *Server) Run() error {\n    return nil\n}\n"
    )
    assert go_imports == ["fmt", "example.com/x/model"]
    assert ("Run", "method", "Server") in [(s[0], s[1], s[4]) for s in go_symbols]


def test_incremental_cache_reuses_unchanged_files(tmp_path):
    write(tmp_path, "a.py", "def a():\n    pass\n")
    b = write(tmp_path, "b.py", "def b():\n    pass\n")
    indexer = ProjectIndexer()

    first = indexer.build_index(tmp_path, history=False)
    assert first.stats.reindexed == 2 and first.stats.reused == 0
    assert (tmp_path / CACHE_RELATIVE).is_file()

    second = indexer.build_index(tmp_path, history=False)
    assert second.stats.reindexed == 0 and second.stats.reused == 2

    b.write_bytes(b"def b():\n    pass\n\ndef c():\n    pass\n")
    stat = b.stat()
    os.utime(b, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    (tmp_path / "a.py").unlink()
    third = indexer.build_index(tmp_path, history=False)
    assert third.stats.reindexed == 1 and third.stats.removed == 1
    assert [s.name for s in third.files["b.py"].symbols] == ["b", "c"]
    assert "removed" in third.stats.summary()


def test_corrupted_cache_is_ignored_and_rebuilt(tmp_path):
    write(tmp_path, "a.py", "def a():\n    pass\n")
    cache = tmp_path / CACHE_RELATIVE
    cache.parent.mkdir(parents=True)
    cache.write_text("{not json", encoding="utf-8")

    index = ProjectIndexer().build_index(tmp_path, history=False)

    assert index.stats.reindexed == 1
    assert json.loads(cache.read_text(encoding="utf-8"))["files"]


def test_generated_dependency_and_symlinked_files_are_skipped(tmp_path):
    write(tmp_path, "main.py", "def main():\n    pass\n")
    write(tmp_path, "proto/api_pb2.py", "x = 1\n")
    write(tmp_path, "gen.py", "# @generated by tool\nx = 1\n")
    write(tmp_path, "node_modules/lib/index.js", "function x() {}\n")
    write(tmp_path, "target/debug/build.rs", "fn main() {}\n")
    outside = write(tmp_path.parent / f"{tmp_path.name}-outside", "secret.py", "def leak(): pass\n")
    try:
        (tmp_path / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pass

    index = ProjectIndexer().build_index(tmp_path, history=False)

    assert set(index.files) == {"main.py"}
    assert index.stats.skipped_generated == 2


def test_change_history_counts_commits(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    try:
        git("init", "-q")
    except (OSError, subprocess.CalledProcessError):
        import pytest
        pytest.skip("git is unavailable")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    target = write(tmp_path, "hot.py", "x = 0\n")
    write(tmp_path, "cold.py", "y = 0\n")
    git("add", ".")
    git("commit", "-qm", "init")
    for value in range(1, 4):
        target.write_bytes(f"x = {value}\n".encode())
        git("commit", "-qam", f"change {value}")

    index = ProjectIndexer().build_index(tmp_path)

    assert index.change_counts["hot.py"] == 4
    assert index.change_counts["cold.py"] == 1


def test_project_map_is_bounded(tmp_path):
    for number in range(50):
        write(tmp_path, f"m{number:02}.py", f"def f{number}():\n    pass\n")
    index = ProjectIndexer().build_index(tmp_path, history=False)
    text = index.project_map(max_chars=300)
    assert len(text) < 400
    assert "more files" in text


def test_context_includes_dependency_of_matched_file(tmp_path):
    write(tmp_path, "checkout.py", "from pricing import total\n\ndef checkout():\n    return total()\n")
    write(tmp_path, "pricing.py", "def total():\n    return 1\n")
    write(tmp_path, "unrelated.py", "def other():\n    return 2\n")

    pack = ContextService().build(ContextRequest("fix checkout flow", tmp_path, 1000))

    by_name = {item.path.name: item for item in pack.items}
    assert "imported by checkout.py" in by_name["pricing.py"].reason
    assert by_name["pricing.py"].score > by_name["unrelated.py"].score
    assert "files indexed" in pack.index_summary


def test_index_panel_filters_symbols_and_shows_relations(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vibe_code.index.panel import IndexPanel

    QApplication.instance() or QApplication([])
    write(tmp_path, "checkout.py", "from pricing import total\n\ndef checkout():\n    return total()\n")
    write(tmp_path, "pricing.py", "def total():\n    return 1\n")
    index = ProjectIndexer().build_index(tmp_path, history=False)
    panel = IndexPanel()
    opened = []
    panel.open_requested.connect(lambda path, line: opened.append((path.name, line)))

    panel.show_index(index)
    assert panel.tree.topLevelItemCount() == 2
    assert "2 files indexed" in panel.stats.text()

    panel.search.setText("total")
    assert panel.tree.topLevelItemCount() == 1
    file_row = panel.tree.topLevelItem(0)
    assert file_row.text(0) == "pricing.py"
    panel.tree.setCurrentItem(file_row)
    assert "checkout.py" in panel.relations.toPlainText()

    panel._activate(file_row.child(0))
    assert opened == [("pricing.py", 1)]
