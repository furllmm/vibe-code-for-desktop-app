from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..index import ProjectIndexer
from ..index.indexer import FileIndex
from .models import ContextItem, ContextPack, ContextRequest

_IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt", ".ini", ".cfg", ".xml", ".ui", ".qml", ".cs", ".cpp",
    ".h", ".hpp", ".rs", ".java", ".kt", ".go",
}


class ContextService:
    """Discover and rank repository text files for a bounded agent context."""

    def __init__(self, indexer: ProjectIndexer | None = None) -> None:
        self._indexer = indexer or ProjectIndexer()

    def build(self, request: ContextRequest) -> ContextPack:
        if request.token_budget <= 0:
            raise ValueError("token_budget must be greater than zero")

        root = request.workspace.expanduser().resolve()
        focus_paths = {p.expanduser().resolve() for p in request.focus_paths}
        index = {
            item.path.resolve(): item
            for item in self._indexer.build(root)
        }
        recent_paths = self._recent_paths(root)
        scored = [
            self._score_metadata(path, request.prompt, focus_paths, index.get(path.resolve()), recent_paths)
            for path in self._discover(root)
        ]
        scored.sort(key=lambda item: (-item.score, str(item.path)))

        budget_chars = request.token_budget * 4
        used = 0
        selected: list[ContextItem] = []
        for item in scored:
            item = self._materialize(item, self._read(item.path))
            size = len(item.content or "")
            if size == 0 or used + size > budget_chars:
                continue
            selected.append(item)
            used += size

        return ContextPack(tuple(selected), used // 4)

    def _discover(self, root: Path) -> list[Path]:
        paths: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file() or any(part in _IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > 512_000:
                    continue
            except OSError:
                continue
            paths.append(path)
        return paths

    def _score_metadata(
        self,
        path: Path,
        prompt: str,
        focus_paths: set[Path],
        indexed: FileIndex | None,
        recent_paths: set[Path],
    ) -> ContextItem:
        terms = {term.lower() for term in re.findall(r"[A-Za-z0-9_]{3,}", prompt)}
        symbol_text = ""
        if indexed is not None:
            symbol_text = " ".join(
                [symbol.name for symbol in indexed.symbols]
                + list(indexed.imports)
            )
        haystack = f"{path.name}\n{symbol_text}".lower()

        resolved = path.resolve()
        score = 100.0 if resolved in focus_paths else 0.0
        reasons = ["explicitly focused"] if resolved in focus_paths else []
        if resolved in recent_paths:
            score += 8
            reasons.append("recent git change")

        for term in terms:
            if term in path.name.lower():
                score += 12
                reasons.append(f"name:{term}")
            elif indexed is not None and any(term in value.lower() for value in (
                [symbol.name for symbol in indexed.symbols] + list(indexed.imports)
            )):
                score += 7
                reasons.append(f"symbol:{term}")
            elif term in haystack:
                score += 2
                reasons.append(f"content:{term}")

        if path.name.lower() in {"readme.md", "pyproject.toml", "package.json"}:
            score += 5
            reasons.append("project metadata")

        matched_symbols = () if indexed is None else tuple(
            symbol for symbol in indexed.symbols
            if any(term in symbol.name.lower() for term in terms)
            and symbol.end_line is not None
        )
        start_line = None
        end_line = None
        if matched_symbols:
            start_line = min(symbol.line for symbol in matched_symbols)
            end_line = max(symbol.end_line or symbol.line for symbol in matched_symbols)
            reasons.append(f"symbol-range:{start_line}-{end_line}")

        return ContextItem(
            path,
            "file",
            score,
            ", ".join(dict.fromkeys(reasons)) or "baseline candidate",
            None,
            start_line,
            end_line,
        )

    @staticmethod
    def _slice_lines(text: str, start_line: int, end_line: int) -> str:
        lines = text.splitlines(keepends=True)
        return "".join(lines[max(0, start_line - 1):end_line])

    @staticmethod
    def _materialize(item: ContextItem, text: str) -> ContextItem:
        if item.start_line is not None and item.end_line is not None:
            lines = text.splitlines(keepends=True)
            text = "".join(lines[max(0, item.start_line - 1):item.end_line])
        return ContextItem(
            item.path, item.kind, item.score, item.reason, text,
            item.start_line, item.end_line,
        )

    @staticmethod
    def _recent_paths(root: Path) -> set[Path]:
        try:
            result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, check=False, capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return set()
        if result.returncode != 0:
            return set()
        paths: set[Path] = set()
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            raw = line[3:]
            if " -> " in raw:
                raw = raw.split(" -> ", 1)[1]
            try:
                candidate = (root / raw).resolve()
                if candidate.is_relative_to(root):
                    paths.add(candidate)
            except (OSError, ValueError):
                continue
        return paths

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
