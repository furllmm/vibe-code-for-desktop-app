from __future__ import annotations
import re
from pathlib import Path
from .models import ContextItem, ContextPack, ContextRequest

_IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
_TEXT_EXTENSIONS = {".py",".js",".ts",".tsx",".jsx",".json",".toml",".yaml",".yml",".md",".txt",".ini",".cfg",".xml",".ui",".qml",".cs",".cpp",".h",".hpp",".rs",".java",".kt",".go"}

class ContextService:
    """Discover and rank repository text files for a bounded agent context."""

    def build(self, request: ContextRequest) -> ContextPack:
        scored = [self._score(p, request.prompt, request.focus_paths) for p in self._discover(request.workspace)]
        scored.sort(key=lambda x: x.score, reverse=True)
        budget_chars = max(4000, request.token_budget * 4)
        used = 0
        selected = []
        for item in scored:
            if item.content is None:
                continue
            size = len(item.content)
            if selected and used + size > budget_chars:
                continue
            selected.append(item)
            used += size
        return ContextPack(tuple(selected), max(1, used // 4))

    def _discover(self, root: Path) -> list[Path]:
        paths = []
        for path in root.rglob("*"):
            if not path.is_file() or any(p in _IGNORE_DIRS for p in path.parts):
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

    def _score(self, path: Path, prompt: str, focus_paths: tuple[Path, ...]) -> ContextItem:
        text = self._read(path)
        terms = {t.lower() for t in re.findall(r"[A-Za-z0-9_]{3,}", prompt)}
        haystack = f"{path.name}\n{text[:12000]}".lower()
        score = 100.0 if path in focus_paths else 0.0
        reasons = ["explicitly focused"] if path in focus_paths else []
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
        return ContextItem(path, "file", score, ", ".join(reasons) or "baseline candidate", text)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
