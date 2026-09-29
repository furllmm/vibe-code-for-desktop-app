from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class ContextItem:
    path: Path
    kind: Literal["file", "directory", "metadata"]
    score: float
    reason: str
    content: str | None = None


@dataclass(frozen=True)
class ContextRequest:
    prompt: str
    workspace: Path
    token_budget: int = 12000
    focus_paths: tuple[Path, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContextPack:
    items: tuple[ContextItem, ...]
    estimated_tokens: int

    def as_text(self) -> str:
        return "\n\n".join(
            f"--- {item.path} ---\n{item.content}"
            for item in self.items
            if item.content is not None
        )
