from __future__ import annotations

import ast
from pathlib import Path
import sys
import tomllib
from typing import Sequence


class PythonPySide6Adapter:
    """Preview adapter for conventional Python/PySide6 desktop projects."""

    def __init__(self, entrypoint: str | None = None) -> None:
        if entrypoint is not None and not entrypoint.strip():
            raise ValueError("entrypoint must not be empty")
        self.entrypoint = entrypoint

    def detect(self, workspace: Path) -> bool:
        if not workspace.is_dir():
            return False
        if not (
            (workspace / "pyproject.toml").is_file()
            or (workspace / "requirements.txt").is_file()
            or any(workspace.glob("*.py"))
        ):
            return False
        if self._has_pyside6_dependency(workspace):
            return True
        checked = 0
        for path in workspace.rglob("*.py"):
            if ".venv" in path.parts or "venv" in path.parts or "node_modules" in path.parts:
                continue
            if self._looks_like_pyside6(path):
                return True
            checked += 1
            if checked >= 1000:
                break
        return False

    def build(self, workspace: Path) -> None:
        """Python does not require a build step for the preview MVP."""
        return None

    def command(self, workspace: Path) -> Sequence[str]:
        target = self._resolve_entrypoint(workspace)
        if target.suffix != ".py":
            raise RuntimeError(f"unsupported Python entrypoint: {target}")
        return (sys.executable, str(target))

    def _resolve_entrypoint(self, workspace: Path) -> Path:
        if self.entrypoint:
            candidate = self._safe_path(workspace, self.entrypoint)
            if not candidate.is_file():
                raise FileNotFoundError(f"Python entrypoint not found: {self.entrypoint}")
            return candidate

        configured = self._entrypoint_from_pyproject(workspace)
        if configured:
            candidate = self._safe_path(workspace, configured)
            if candidate.is_file() and candidate.suffix == ".py":
                return candidate

        candidates = [
            workspace / "main.py",
            workspace / "app.py",
            workspace / "src" / "main.py",
            workspace / "src" / "app.py",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        raise RuntimeError(
            "Could not detect a Python entrypoint. "
            "Set the preview entrypoint explicitly."
        )

    @staticmethod
    def _safe_path(workspace: Path, raw: str) -> Path:
        candidate = (workspace / raw).resolve()
        root = workspace.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("preview entrypoint must stay inside the workspace")
        return candidate

    @staticmethod
    def _entrypoint_from_pyproject(workspace: Path) -> str | None:
        path = workspace / "pyproject.toml"
        if not path.is_file():
            return None
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return None

        scripts = data.get("project", {}).get("scripts", {})
        if not isinstance(scripts, dict):
            return None

        # An explicitly named preview script may point to module:function.
        raw = scripts.get("preview")
        if not isinstance(raw, str) or ":" not in raw:
            return None
        module = raw.split(":", 1)[0].strip()
        if not module or any(part in {".", ".."} for part in module.split(".")):
            return None
        candidate = workspace.joinpath(*module.split(".")).with_suffix(".py")
        return str(candidate.relative_to(workspace))

    @staticmethod
    def _has_pyside6_dependency(workspace: Path) -> bool:
        requirements = workspace / "requirements.txt"
        if requirements.is_file():
            try:
                if any(
                    line.strip().lower().replace("-", "").startswith("pyside6")
                    for line in requirements.read_text(encoding="utf-8", errors="replace").splitlines()
                ):
                    return True
            except OSError:
                pass

        pyproject = workspace / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError):
                data = {}
            dependencies = data.get("project", {}).get("dependencies", [])
            if isinstance(dependencies, list) and any(
                isinstance(dep, str) and dep.lower().replace("-", "").startswith("pyside6")
                for dep in dependencies
            ):
                return True
        return False

    @staticmethod
    def _looks_like_pyside6(path: Path) -> bool:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return False
        return any(
            isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("PySide6")
            or isinstance(node, ast.Import)
            and any(alias.name.startswith("PySide6") for alias in node.names)
            for node in ast.walk(tree)
        )
