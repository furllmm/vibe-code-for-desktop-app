from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoveryAction(str, Enum):
    FIX = "fix"
    REVERT = "revert"
    KEEP = "keep"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    failure_cycle: int
    change_ids: tuple[str, ...]
