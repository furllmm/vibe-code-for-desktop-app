from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    line: int


@dataclass(frozen=True)
class FileIndex:
    path: Path
    language: str
    symbols: tuple[Symbol, ...] = field(default_factory=tuple)
    imports: tuple[str, ...] = field(default_factory=tuple)


class ProjectIndexer:
    """Lightweight structural index. Python gets AST symbols; other languages get metadata."""

    def build(self, root: Path) -> tuple[FileIndex, ...]:
        root = root.expanduser().resolve()
        results: list[FileIndex] = []
        for path in root.rglob("*"):
            if not path.is_file() or any(
                part in {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
                for part in path.parts
            ):
                continue
            language = self._language(path)
            if language is None:
                continue
            if language == "python":
                results.append(self._index_python(path))
            else:
                results.append(FileIndex(path, language))
        return tuple(results)

    def _index_python(self, path: Path) -> FileIndex:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, UnicodeError):
            return FileIndex(path, "python")

        symbols: list[Symbol] = []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(Symbol(node.name, "function", node.lineno))
            elif isinstance(node, ast.ClassDef):
                symbols.append(Symbol(node.name, "class", node.lineno))
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        symbols.sort(key=lambda item: (item.line, item.name))
        return FileIndex(path, "python", tuple(symbols), tuple(sorted(set(imports))))

    @staticmethod
    def _language(path: Path) -> str | None:
        return {
            ".py": "python",
            ".rs": "rust",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".go": "go",
            ".java": "java",
            ".kt": "kotlin",
        }.get(path.suffix.lower())
