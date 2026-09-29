from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class AgentMessage:
    role: str
    content: str

class AIProvider(Protocol):
    def complete(self, messages: list[AgentMessage]) -> str:
        ...
