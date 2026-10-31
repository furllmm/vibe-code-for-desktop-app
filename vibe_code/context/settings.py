"""Per-workspace context configuration: budgets, exclusions and project rules."""
from __future__ import annotations

import fnmatch
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SETTINGS_RELATIVE = Path(".vibe-code") / "context.json"
IGNORE_FILE = ".vibeignore"
RULE_FILES = (Path(".vibe-code") / "rules.md", Path("AGENTS.md"))
DEFAULT_TOKEN_BUDGET = 12_000
MIN_TOKEN_BUDGET = 500
MAX_TOKEN_BUDGET = 200_000
MAX_RULES_CHARS = 8_000

_TOKEN_PIECE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def estimate_tokens(text: str) -> int:
    """Approximate BPE token count without a tokenizer dependency.

    Words are roughly one token per six characters, digits per three, and each
    punctuation/symbol character is usually its own token. Calibrated to stay at or
    above common tokenizers for source code so budgets are not exceeded.
    """
    if not text:
        return 0
    total = 0
    for piece in _TOKEN_PIECE.findall(text):
        if piece[0].isalpha():
            total += max(1, math.ceil(len(piece) / 6))
        elif piece[0].isdigit():
            total += max(1, math.ceil(len(piece) / 3))
        else:
            total += 1
    return max(total, math.ceil(len(text) / 6))


@dataclass(frozen=True)
class ContextSettings:
    token_budget: int = DEFAULT_TOKEN_BUDGET
    exclude: tuple[str, ...] = field(default_factory=tuple)
    include_rules: bool = True
    errors: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, root: Path) -> "ContextSettings":
        errors: list[str] = []
        data: dict = {}
        path = root / SETTINGS_RELATIVE
        if path.is_file() and not path.is_symlink():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    errors.append(f"{SETTINGS_RELATIVE.as_posix()} must contain a JSON object")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"{SETTINGS_RELATIVE.as_posix()} ignored: {exc}")
        budget = data.get("token_budget", DEFAULT_TOKEN_BUDGET)
        if not isinstance(budget, int) or isinstance(budget, bool) or not MIN_TOKEN_BUDGET <= budget <= MAX_TOKEN_BUDGET:
            if "token_budget" in data:
                errors.append(f"token_budget must be an integer between {MIN_TOKEN_BUDGET} and {MAX_TOKEN_BUDGET}")
            budget = DEFAULT_TOKEN_BUDGET
        patterns = [p for p in data.get("exclude", []) if isinstance(p, str) and p.strip()]
        ignore = root / IGNORE_FILE
        if ignore.is_file() and not ignore.is_symlink():
            try:
                for line in ignore.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{IGNORE_FILE} ignored: {exc}")
        include_rules = data.get("include_rules", True) is not False
        return cls(budget, tuple(patterns), include_rules, tuple(errors))

    def is_excluded(self, relative: PurePosixPath) -> bool:
        text = relative.as_posix()
        for raw in self.exclude:
            pattern = raw.strip().lstrip("/")
            if pattern.endswith("/"):
                prefix = pattern.rstrip("/")
                if text.startswith(prefix + "/") or f"/{prefix}/" in f"/{text}":
                    return True
                continue
            if fnmatch.fnmatchcase(text, pattern) or fnmatch.fnmatchcase(relative.name, pattern):
                return True
            if "/" in pattern and fnmatch.fnmatchcase(text, pattern + "/*"):
                return True
        return False

    def load_rules(self, root: Path) -> tuple[Path, str] | None:
        if not self.include_rules:
            return None
        for relative in RULE_FILES:
            path = root / relative
            if path.is_file() and not path.is_symlink():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    continue
                if text:
                    return path, text[:MAX_RULES_CHARS]
        return None
