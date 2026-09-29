from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .process import ProcessManager, ProcessResult


@dataclass(frozen=True)
class PreviewConfig:
    command: tuple[str, ...]


class PreviewAdapter(Protocol):
    def detect(self, workspace: Path) -> bool:
        ...

    def build(self, workspace: Path) -> None:
        ...

    def command(self, workspace: Path) -> Sequence[str]:
        ...


class GenericPreviewAdapter:
    """Minimal explicit-command adapter for the first preview MVP."""

    def __init__(self, config: PreviewConfig) -> None:
        if not config.command:
            raise ValueError("preview command must not be empty")
        self.config = config

    def detect(self, workspace: Path) -> bool:
        return workspace.is_dir()

    def build(self, workspace: Path) -> None:
        return None

    def command(self, workspace: Path) -> Sequence[str]:
        return self.config.command


class PreviewEngine:
    """Build and run one desktop preview process."""

    def __init__(self, workspace: Path, adapter: PreviewAdapter) -> None:
        self.workspace = workspace.resolve()
        self.adapter = adapter
        self.process = ProcessManager(self.workspace)

    @property
    def running(self) -> bool:
        return self.process.running

    def build(self) -> None:
        if not self.adapter.detect(self.workspace):
            raise RuntimeError("preview adapter does not support this workspace")
        self.adapter.build(self.workspace)

    def start(self) -> None:
        self.process.start(self.adapter.command(self.workspace))

    def restart(self) -> None:
        self.stop()
        self.start()

    def stop(self) -> ProcessResult | None:
        return self.process.stop()

    def poll(self) -> ProcessResult | None:
        return self.process.poll()

    def read_logs(self) -> str:
        return self.process.read_available()
