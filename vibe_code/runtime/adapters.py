from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CommandSpec:
    command: tuple[str, ...]
    build_command: tuple[str, ...] = ()


class CommandProjectAdapter:
    """Small adapter for toolchain-driven desktop projects.

    Commands are argv tuples, never shell strings. This keeps the preview
    process predictable and avoids shell interpolation.
    """

    def __init__(
        self,
        *,
        marker_files: tuple[str, ...],
        command: tuple[str, ...],
        build_command: tuple[str, ...] = (),
    ) -> None:
        if not marker_files:
            raise ValueError("marker_files must not be empty")
        if not command:
            raise ValueError("command must not be empty")
        self.marker_files = marker_files
        self.spec = CommandSpec(command, build_command)

    def detect(self, workspace: Path) -> bool:
        return workspace.is_dir() and any(
            (workspace / marker).is_file() for marker in self.marker_files
        )

    def build(self, workspace: Path) -> None:
        if not self.spec.build_command:
            return
        from .process import ProcessManager

        process = ProcessManager(workspace)
        process.start(self.spec.build_command)
        try:\n            result = process.wait(timeout=120.0)\n        except subprocess.TimeoutExpired:\n            process.stop()\n            raise RuntimeError("Preview build timed out after 120 seconds")
        if result.returncode != 0:
            output = process.read_available().strip()
            raise RuntimeError(
                f"Preview build failed with exit code {result.returncode}"
                + (f":\n{output}" if output else "")
            )

    def command(self, workspace: Path) -> Sequence[str]:
        return self.spec.command


class RustAdapter(CommandProjectAdapter):
    def __init__(self) -> None:
        super().__init__(
            marker_files=("Cargo.toml",),
            command=("cargo", "run"),
            build_command=("cargo", "build"),
        )


class GoAdapter(CommandProjectAdapter):
    def __init__(self) -> None:
        super().__init__(
            marker_files=("go.mod",),
            command=("go", "run", "."),
        )


class DotNetAdapter(CommandProjectAdapter):
    def __init__(self) -> None:
        super().__init__(
            marker_files=("*.csproj", "*.fsproj", "*.sln"),
            command=("dotnet", "run"),
        )

    def detect(self, workspace: Path) -> bool:
        if not workspace.is_dir():
            return False
        return any(workspace.glob(pattern) for pattern in self.marker_files)


class NodeElectronAdapter(CommandProjectAdapter):
    def __init__(self) -> None:
        super().__init__(
            marker_files=("package.json",),
            command=("npm", "run", "start"),
        )

    def detect(self, workspace: Path) -> bool:
        if not super().detect(workspace):
            return False
        package = workspace / "package.json"
        try:
            import json

            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return False
        deps = {}
        for key in ("dependencies", "devDependencies"):
            value = data.get(key, {})
            if isinstance(value, dict):
                deps.update(value)
        return "electron" in deps and isinstance(data.get("scripts", {}).get("start"), str)
