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
    start_line: int | None = None
    end_line: int | None = None

    @property
    def line_range(self) -> str:
        if self.start_line is None or self.end_line is None:
            return ""
        if self.start_line == self.end_line:
            return f"L{self.start_line}"
        return f"L{self.start_line}-{self.end_line}"


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
        sections: list[str] = []
        for item in self.items:
            if item.content is None:
                continue
            location = f" ({item.line_range})" if item.line_range else ""
            sections.append(
                f"--- {item.path}{location} ---\n{item.content}"
            )
        return "\n\n".join(sections)

    def summary(self) -> str:
        return (
            f"{len(self.items)} context items, "
            f"~{self.estimated_tokens} estimated tokens"
        )
