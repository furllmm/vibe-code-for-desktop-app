from __future__ import annotations

import os
import shlex
from pathlib import Path

from .adapters import (
    AdapterRegistry,
    DotNetAdapter,
    ElectronAdapter,
    GoAdapter,
    NodeScriptAdapter,
    RustCargoAdapter,
)
from .native_adapters import CMakeAdapter, CppAdapter, JavaAdapter
from .preview import GenericPreviewAdapter, PreviewAdapter, PreviewConfig
from .python_adapter import PythonPySide6Adapter


def adapter_from_environment() -> PreviewAdapter | None:
    """Return the explicitly configured preview adapter, if any."""
    command_text = os.environ.get("VIBE_CODE_PREVIEW_COMMAND", "").strip()
    if not command_text:
        return None
    command = tuple(shlex.split(command_text))
    if not command:
        raise ValueError("VIBE_CODE_PREVIEW_COMMAND must not be empty")
    return GenericPreviewAdapter(PreviewConfig(command))


def default_adapters() -> tuple[PreviewAdapter, ...]:
    entrypoint = os.environ.get("VIBE_CODE_PYTHON_ENTRYPOINT") or None
    return (
        PythonPySide6Adapter(entrypoint),
        CMakeAdapter(),
        JavaAdapter(),
        RustCargoAdapter(),
        GoAdapter(),
        DotNetAdapter(),
        ElectronAdapter(),
        NodeScriptAdapter(),
        CppAdapter(),
    )


def detect_preview_adapter(workspace: Path) -> PreviewAdapter | None:
    """Choose a deterministic adapter: explicit override first, then manifests."""
    configured = adapter_from_environment()
    if configured is not None:
        return configured
    return AdapterRegistry(default_adapters()).detect(workspace)
