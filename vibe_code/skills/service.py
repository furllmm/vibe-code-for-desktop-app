from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_BUILTIN_ROOT = Path(__file__).resolve().parent / "builtin"
_IGNORE_PARTS = {".git", ".venv", "node_modules", "__pycache__"}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    content: str
    score: int


class SkillService:
    """Discover skill metadata first, then load only the best relevant SKILL.md files."""

    def __init__(self, *, max_skills: int = 2, max_chars_per_skill: int = 6000) -> None:
        if max_skills < 1 or max_chars_per_skill < 500:
            raise ValueError("skill limits are too small")
        self.max_skills = max_skills
        self.max_chars_per_skill = max_chars_per_skill

    def load_for_prompt(self, workspace: Path, prompt: str) -> tuple[Skill, ...]:
        lowered = prompt.lower()
        terms = {self._stem(term) for term in re.findall(r"[a-zA-Z0-9_+-]{3,}", lowered)}
        words = set(re.findall(r"[a-z0-9]+", lowered))
        candidates: list[tuple[int, Path, str, str]] = []
        roots = (workspace / ".vibe-code" / "skills", _BUILTIN_ROOT)
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("SKILL.md"):
                if any(part in _IGNORE_PARTS for part in path.parts):
                    continue
                try:
                    relative = path.relative_to(root)
                    raw = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError, ValueError):
                    continue
                name, description, body = self._metadata(raw, relative.parent.name)
                key = name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                searchable = f"{name} {description}".lower()
                keywords = {
                    self._stem(word) for word in re.findall(r"[a-zA-Z0-9_+-]{3,}", searchable)
                }
                searchable_words = set(re.findall(r"[a-z0-9]+", searchable))
                score = len(terms & keywords) * 4
                if words & {"ui", "interface", "screen", "layout"} and "ui" in searchable_words:
                    score += 3
                if words & {"bug", "crash", "error", "fix"} and "debug" in searchable:
                    score += 3
                candidates.append((score, path, name, description + "\n\n" + body))
        candidates.sort(key=lambda item: (-item[0], item[2].casefold(), str(item[1])))
        top_score = candidates[0][0] if candidates else 0
        threshold = max(1, (top_score + 1) // 2)
        selected: list[Skill] = []
        for score, path, name, content in candidates:
            if len(selected) >= self.max_skills or score < threshold:
                continue
            description, _, body = content.partition("\n\n")
            selected.append(Skill(name, description, path, body[:self.max_chars_per_skill], score))
        return tuple(selected)

    @staticmethod
    def _stem(word: str) -> str:
        for suffix in ("ing", "es", "s"):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                return word[: -len(suffix)]
        return word

    @staticmethod
    def _metadata(raw: str, fallback_name: str) -> tuple[str, str, str]:
        lines = raw.splitlines()
        name = fallback_name.replace("-", " ").title()
        description = ""
        if lines and lines[0].strip() == "---":
            end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
            if end is not None:
                for line in lines[1:end]:
                    key, sep, value = line.partition(":")
                    if sep and key.strip().lower() == "name":
                        name = value.strip().strip("\"'")
                    elif sep and key.strip().lower() == "description":
                        description = value.strip().strip("\"'")
                lines = lines[end + 1:]
        if not description:
            description = next((line.lstrip("# ").strip() for line in lines if line.strip()), name)
        return name, description, "\n".join(lines).strip()
