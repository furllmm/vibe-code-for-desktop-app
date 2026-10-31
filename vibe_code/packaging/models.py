from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackageRequest:
    backend: str
    name: str
    output_dir: str = "dist"
    entrypoint: str | None = None
    one_file: bool = False
    package_type: str = "app-image"


@dataclass(frozen=True)
class PackagingPlan:
    backend: str
    command: tuple[str, ...]
    output_dir: Path
    description: str
    timeout_seconds: int = 1800


@dataclass(frozen=True)
class PackagingResult:
    success: bool
    output: str
    output_dir: Path
    returncode: int | None
