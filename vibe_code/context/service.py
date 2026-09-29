from __future__ import annotations

import re
from pathlib import Path

from .models import ContextItem, ContextPack, ContextRequest

_IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt", ".ini", ".cfg", ".xml", ".ui", ".qml", ".cs", ".cpp",
    ".h", ".hpp", ".rs", ".java", ".kt", ".go",
}


class ContextService:
    """Discover and rank repository text files for a bounded agent context."""

    def build(self, request: ContextRequest) -> ContextPack:
        if request.token_budget <= 0:
            raise ValueError("token_budget must be greater than zero")

        root = request.workspace.expanduser().resolve()
        focus_paths = {p.expanduser().resolve() for p in request.focus_paths}
        scored = [
            self._score(path, request.prompt, focus_paths)
            for path in self._discover(root)
        ]
        scored.sort(key=lambda item: (-item.score, str(item.path)))

        budget_chars = request.token_budget * 4
        used = 0
        selected: list[ContextItem] = []
        for item in scored:
            if item.content is None:
                continue
            size = len(item.content)
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

    def _score(
        self,
        path: Path,
        prompt: str,
        focus_paths: set[Path],
    ) -> ContextItem:
        text = self._read(path)
        terms = {term.lower() for term in re.findall(r"[A-Za-z0-9_]{3,}", prompt)}
        haystack = f"{path.name}\n{text[:12000]}".lower()
        score = 100.0 if path.resolve() in focus_paths else 0.0
        reasons = ["explicitly focused"] if path.resolve() in focus_paths else []

        for term in terms:
            if term in path.name.lower():
                score += 12
                reasons.append(f"name:{term}")
            elif term in haystack:
                score += 2
                reasons.append(f"content:{term}")

        if path.name.lower() in {"readme.md", "pyproject.toml", "package.json"}:
            score += 5
            reasons.append("project metadata")

        return ContextItem(
            path, "file", score, ", ".join(reasons) or "baseline candidate", text
        )

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
