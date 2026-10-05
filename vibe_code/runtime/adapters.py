from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
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
        try:
            result = process.wait(timeout=120.0)
        except subprocess.TimeoutExpired:
            process.stop()
            raise RuntimeError("Preview build timed out after 120 seconds")
        if result.returncode != 0:
            output = process.read_available().strip()
            raise RuntimeError(
                f"Preview build failed with exit code {result.returncode}"
                + (f":\\n{output}" if output else "")
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


class CppAdapter(CommandProjectAdapter):
    """Preview a small self-contained C/C++ project with a conventional main file."""

    _sources = ("main.cpp", "main.cc", "main.cxx", "main.c")

    def __init__(self) -> None:
        super().__init__(
            marker_files=self._sources,
            command=("g++", ".vibe-code/build/preview"),
            build_command=(),
        )

    def detect(self, workspace: Path) -> bool:
        return workspace.is_dir() and any((workspace / name).is_file() for name in self._sources)

    def build(self, workspace: Path) -> None:
        source = next(
            (workspace / name for name in self._sources if (workspace / name).is_file()),
            None,
        )
        if source is None:
            raise RuntimeError("No conventional C/C++ entrypoint found")
        output = workspace / ".vibe-code" / "build" / "preview"
        output.parent.mkdir(parents=True, exist_ok=True)
        compiler = "gcc" if source.suffix == ".c" else "g++"
        process = subprocess.run(
            (compiler, str(source), "-O0", "-g", "-o", str(output)),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120.0,
            check=False,
        )
        if process.returncode != 0:
            diagnostics = (process.stdout + process.stderr).strip()
            raise RuntimeError(
                f"C/C++ build failed with exit code {process.returncode}"
                + (f":\\n{diagnostics}" if diagnostics else "")
            )

    def command(self, workspace: Path) -> Sequence[str]:
        output = workspace / ".vibe-code" / "build" / "preview"
        if not output.is_file():
            raise RuntimeError("Build the C/C++ preview before starting it")
        return (str(output),)


class JavaGradleAdapter(CommandProjectAdapter):
    """Detect Gradle desktop projects that explicitly use the application plugin."""

    def __init__(self) -> None:
        super().__init__(
            marker_files=("build.gradle", "build.gradle.kts"),
            command=("./gradlew", "run"),
        )

    def detect(self, workspace: Path) -> bool:
        if not workspace.is_dir():
            return False
        wrapper = workspace / "gradlew"
        if not wrapper.is_file():
            return False
        for marker in self.marker_files:
            path = workspace / marker
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                if "application" in text and "mainClass" in text:
                    return True
        return False


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
        scripts = data.get("scripts", {})
        return "electron" in deps and isinstance(scripts, dict) and isinstance(scripts.get("start"), str)
