from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from typing import Sequence


class BuildCommandAdapter:
    """Shared safe subprocess build runner for language-specific adapters."""

    build_timeout = 300

    def _build(self, workspace: Path, command: Sequence[str]) -> None:
        try:
            result = subprocess.run(
                list(command),
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.build_timeout,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Build tool not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Build timed out after {self.build_timeout}s.\n{str(output)[-8000:]}"
            ) from exc
        if result.returncode:
            raise RuntimeError(
                f"Build failed (exit {result.returncode}).\n{result.stdout[-8000:]}"
            )


class RustCargoAdapter(BuildCommandAdapter):
    def detect(self, workspace: Path) -> bool:
        return (workspace / "Cargo.toml").is_file()

    def _package_name(self, workspace: Path) -> str:
        try:
            data = tomllib.loads((workspace / "Cargo.toml").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise RuntimeError(f"Could not read Cargo.toml: {exc}") from exc
        package = data.get("package", {})
        name = package.get("name") if isinstance(package, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("Cargo.toml must define [package].name for preview")
        return name

    def build(self, workspace: Path) -> None:
        self._build(workspace, ("cargo", "build", "--manifest-path", str(workspace / "Cargo.toml")))

    def command(self, workspace: Path) -> Sequence[str]:
        name = self._package_name(workspace)
        executable = workspace / "target" / "debug" / name
        if os.name == "nt":
            executable = executable.with_suffix(".exe")
        if not executable.is_file():
            raise RuntimeError("Rust preview executable is missing; build the project first")
        return (str(executable),)


class GoAdapter(BuildCommandAdapter):
    output_relative = Path(".vibe-code") / "bin" / ("preview.exe" if os.name == "nt" else "preview")

    def detect(self, workspace: Path) -> bool:
        return (workspace / "go.mod").is_file()

    def build(self, workspace: Path) -> None:
        output = workspace / self.output_relative
        output.parent.mkdir(parents=True, exist_ok=True)
        self._build(workspace, ("go", "build", "-o", str(output), "."))

    def command(self, workspace: Path) -> Sequence[str]:
        executable = workspace / self.output_relative
        if not executable.is_file():
            raise RuntimeError("Go preview executable is missing; build the project first")
        return (str(executable),)


class DotNetAdapter(BuildCommandAdapter):
    def __init__(self) -> None:
        self.project: Path | None = None
        self.assembly_name: str | None = None
        self.target_framework: str | None = None

    def detect(self, workspace: Path) -> bool:
        projects = sorted(workspace.glob("*.csproj"))
        if not projects:
            return False
        self.project = projects[0]
        try:
            root = ET.parse(self.project).getroot()
        except (OSError, ET.ParseError):
            return True
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "AssemblyName" and node.text:
                self.assembly_name = node.text.strip()
            elif tag == "TargetFramework" and node.text:
                self.target_framework = node.text.strip()
        if self.assembly_name is None:
            self.assembly_name = self.project.stem
        return True

    def _project_path(self, workspace: Path) -> Path:
        if self.project is None or not self.project.is_file():
            self.detect(workspace)
        if self.project is None:
            raise RuntimeError("No .csproj project found")
        return self.project

    def build(self, workspace: Path) -> None:
        project = self._project_path(workspace)
        self._build(workspace, ("dotnet", "build", str(project), "--nologo"))

    def command(self, workspace: Path) -> Sequence[str]:
        project = self._project_path(workspace)
        if not self.target_framework:
            try:
                root = ET.parse(project).getroot()
            except (OSError, ET.ParseError) as exc:
                raise RuntimeError("Could not read .NET target framework") from exc
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] == "TargetFramework" and node.text:
                    self.target_framework = node.text.strip()
                    break
        if not self.target_framework:
            raise RuntimeError("Only projects with a single TargetFramework are supported")
        assembly = self.assembly_name or project.stem
        dll = workspace / "bin" / "Debug" / self.target_framework / f"{assembly}.dll"
        if not dll.is_file():
            raise RuntimeError("Built .NET assembly is missing; build the project first")
        return ("dotnet", str(dll))


class ElectronAdapter:
    def detect(self, workspace: Path) -> bool:
        package = workspace / "package.json"
        electron = workspace / "node_modules" / "electron" / "cli.js"
        if not package.is_file() or not electron.is_file():
            return False
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        dependencies = data.get("dependencies", {})
        dev_dependencies = data.get("devDependencies", {})
        return "electron" in dependencies or "electron" in dev_dependencies

    def build(self, workspace: Path) -> None:
        # Electron projects may define arbitrary packaging scripts; do not run them implicitly.
        return None

    def command(self, workspace: Path) -> Sequence[str]:
        cli = workspace / "node_modules" / "electron" / "cli.js"
        if not cli.is_file():
            raise RuntimeError("Local Electron installation not found; install dependencies first")
        return ("node", str(cli), ".")


class NodeScriptAdapter:
    def detect(self, workspace: Path) -> bool:
        package = workspace / "package.json"
        if not package.is_file():
            return False
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        scripts = data.get("scripts", {})
        return isinstance(scripts, dict) and isinstance(scripts.get("start"), str)

    def build(self, workspace: Path) -> None:
        # Package managers and lifecycle scripts are user-controlled; no implicit install/build.
        return None

    def command(self, workspace: Path) -> Sequence[str]:
        package = workspace / "package.json"
        data = json.loads(package.read_text(encoding="utf-8"))
        script = data["scripts"]["start"]
        if not isinstance(script, str) or not script.strip():
            raise RuntimeError("package.json scripts.start must be a non-empty string")
        # npm executes the declared script; this is an explicit project-run action.
        return ("npm", "run", "start")


class AdapterRegistry:
    """Ordered project detection; more specific adapters must be registered first."""

    def __init__(self, adapters: Sequence[object]) -> None:
        self.adapters = tuple(adapters)

    def detect(self, workspace: Path):
        root = workspace.resolve()
        for adapter in self.adapters:
            try:
                if adapter.detect(root):
                    return adapter
            except (OSError, ValueError, RuntimeError):
                continue
        return None
