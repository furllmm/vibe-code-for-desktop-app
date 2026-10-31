from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

from ..index import ProjectIndex, ProjectIndexer
from ..index.indexer import IGNORED_DIRS, FileIndex
from ..security import is_sensitive_path, redact_secrets
from .models import ContextItem, ContextPack, ContextRequest
from .settings import ContextSettings, estimate_tokens

_IGNORE_DIRS = set(IGNORED_DIRS)
_RELATED_BOOST = 6.0
_RELATED_SEEDS = 5
_MAX_CONTEXT_FILES = 20_000
_MAX_CONTEXT_SCAN_BYTES = 256 * 1024 * 1024
_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt", ".ini", ".cfg", ".xml", ".ui", ".qml", ".cs", ".cpp",
    ".h", ".hpp", ".rs", ".java", ".kt", ".go",
}


class ContextService:
    """Discover and rank repository text files for a bounded agent context."""

    def __init__(self, indexer: ProjectIndexer | None = None) -> None:
        self._indexer = indexer or ProjectIndexer()
        self.last_index: ProjectIndex | None = None

    def build(self, request: ContextRequest) -> ContextPack:
        if request.token_budget <= 0:
            raise ValueError("token_budget must be greater than zero")

        root = request.workspace.expanduser().resolve()
        settings = ContextSettings.load(root)
        focus_paths = {p.expanduser().resolve() for p in request.focus_paths}
        project_index = self._build_index(root)
        self.last_index = project_index
        index = {item.path.resolve(): item for item in project_index.files.values()} if project_index else {
            item.path.resolve(): item for item in self._indexer.build(root)
        }
        recent_paths = self._recent_paths(root)
        scored = [
            self._score_metadata(path, request.prompt, focus_paths, index.get(path.resolve()), recent_paths)
            for path in self._discover(root, settings)
        ]
        if project_index is not None:
            scored = self._apply_graph_signals(root, scored, project_index)
        scored.sort(key=lambda item: (-item.score, str(item.path)))

        used = 0
        redactions = 0
        selected: list[ContextItem] = []
        rules = settings.load_rules(root)
        if rules is not None:
            rules_path, rules_text = rules
            cost = estimate_tokens(rules_text)
            if cost <= request.token_budget // 4:
                selected.append(ContextItem(rules_path, "metadata", 1000.0, "project coding rules", rules_text))
                used += cost
        for item in scored:
            text, replaced = redact_secrets(self._read(item.path))
            item = self._materialize(item, text)
            cost = estimate_tokens(item.content or "")
            if cost == 0 or used + cost > request.token_budget:
                continue
            if replaced and item.content and "[REDACTED]" in item.content:
                item = ContextItem(
                    item.path, item.kind, item.score, f"{item.reason}, secrets redacted",
                    item.content, item.start_line, item.end_line,
                )
                redactions += item.content.count("[REDACTED]")
            selected.append(item)
            used += cost

        summary = project_index.stats.summary() if project_index is not None else ""
        return ContextPack(tuple(selected), used, summary, redactions, settings.errors)

    def _build_index(self, root: Path) -> ProjectIndex | None:
        build_index = getattr(self._indexer, "build_index", None)
        if build_index is None:
            return None
        try:
            return build_index(root)
        except OSError:
            return None

    @staticmethod
    def _apply_graph_signals(
        root: Path, scored: list[ContextItem], project_index: ProjectIndex
    ) -> list[ContextItem]:
        def relative(path: Path) -> str:
            return path.resolve().relative_to(root).as_posix()

        ranked = sorted(scored, key=lambda item: -item.score)
        seeds = [relative(item.path) for item in ranked[:_RELATED_SEEDS] if item.score >= 7]
        boosts: dict[str, list[str]] = {}
        for seed in seeds:
            for target in project_index.dependencies.get(seed, ()):
                boosts.setdefault(target, []).append(f"imported by {seed}")
            for source in project_index.dependents.get(seed, ()):
                boosts.setdefault(source, []).append(f"imports {seed}")
        result: list[ContextItem] = []
        for item in scored:
            key = relative(item.path)
            score = item.score
            reasons = [] if item.reason == "baseline candidate" else [item.reason]
            if key in boosts and key not in seeds:
                score += _RELATED_BOOST
                reasons.append(boosts[key][0])
            changes = project_index.change_counts.get(key, 0)
            if changes >= 3:
                score += min(4.0, changes / 5)
                reasons.append(f"changed in {changes} recent commits")
            result.append(ContextItem(
                item.path, item.kind, score, ", ".join(reasons) or "baseline candidate",
                item.content, item.start_line, item.end_line,
            ))
        return result

    def _discover(self, root: Path, settings: ContextSettings | None = None) -> list[Path]:
        settings = settings or ContextSettings()
        paths: list[Path] = []
        scanned_bytes = 0
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if any(part in _IGNORE_DIRS for part in relative.parts):
                continue
            if is_sensitive_path(relative) or settings.is_excluded(PurePosixPath(relative.as_posix())):
                continue
            if path.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 512_000:
                continue
            if len(paths) >= _MAX_CONTEXT_FILES or scanned_bytes + size > _MAX_CONTEXT_SCAN_BYTES:
                break
            paths.append(path)
            scanned_bytes += size
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
