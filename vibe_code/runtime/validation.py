from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .preview import PreviewEngine


MAX_LOG_CHARS = 64 * 1024


@dataclass(frozen=True)
class ValidationStep:
    name: str
    success: bool
    output: str
    skipped: bool = False


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    steps: tuple[ValidationStep, ...]
    preview_running: bool

    @property
    def output(self) -> str:
        sections = []
        for step in self.steps:
            status = "SKIPPED" if step.skipped else "OK" if step.success else "FAILED"
            sections.append(f"[{status}] {step.name}\n{step.output}".rstrip())
        return "\n\n".join(sections)[-MAX_LOG_CHARS:]


class ProjectValidator:
    """Run known project test commands, the configured build, and a preview smoke check.

    This class must only be used after the user explicitly trusts the workspace.
    Commands are fixed by project type and always launched without a shell.
    """

    def __init__(
        self,
        workspace: Path,
        preview: PreviewEngine,
        *,
        test_timeout: float = 300.0,
        startup_timeout: float = 2.0,
    ) -> None:
        self.workspace = workspace.resolve()
        self.preview = preview
        self.test_timeout = test_timeout
        self.startup_timeout = startup_timeout
        if test_timeout <= 0 or startup_timeout <= 0:
            raise ValueError("validation timeouts must be greater than zero")
        if preview.workspace != self.workspace:
            raise ValueError("preview engine belongs to a different workspace")

    def run(self) -> ValidationResult:
        steps: list[ValidationStep] = []
        test_command = self._test_command()
        if test_command is None:
            steps.append(ValidationStep(
                "Tests", True,
                "No supported test manifest or test directory was detected; tests were skipped.",
                skipped=True,
            ))
        else:
            test_step = self._run_command("Tests", test_command)
            steps.append(test_step)
            if not test_step.success:
                self.preview.stop()
                return ValidationResult(False, tuple(steps), False)

        try:
            self.preview.stop()
            self.preview.build()
            steps.append(ValidationStep("Build", True, "Build completed successfully."))
        except Exception as exc:
            steps.append(ValidationStep("Build", False, str(exc)[-MAX_LOG_CHARS:]))
            self.preview.stop()
            return ValidationResult(False, tuple(steps), False)

        post_build_command = self._post_build_test_command()
        if post_build_command is not None:
            post_build = self._run_command("Build-system tests", post_build_command)
            steps.append(post_build)
            if not post_build.success:
                self.preview.stop()
                return ValidationResult(False, tuple(steps), False)

        try:
            self.preview.start()
        except Exception as exc:
            steps.append(ValidationStep("Preview startup", False, str(exc)))
            return ValidationResult(False, tuple(steps), False)

        deadline = time.monotonic() + self.startup_timeout
        logs = ""
        while time.monotonic() < deadline:
            logs += self.preview.read_logs()
            status = self.preview.poll()
            if status is not None:
                logs += self.preview.read_logs()
                success = not status.crashed
                steps.append(ValidationStep(
                    "Preview smoke check",
                    success,
                    (logs or "Preview exited cleanly.") +
                    f"\nExit code: {status.returncode}",
                ))
                return ValidationResult(success, tuple(steps), False)
            time.sleep(0.025)

        logs += self.preview.read_logs()
        steps.append(ValidationStep(
            "Preview smoke check", True,
            (logs or "Preview remained alive during the startup window.") +
            f"\nStartup window: {self.startup_timeout:g}s",
        ))
        return ValidationResult(True, tuple(steps), self.preview.running)

    def _test_command(self) -> tuple[str, ...] | None:
        root = self.workspace
        if (root / "Cargo.toml").is_file():
            return ("cargo", "test", "--manifest-path", str(root / "Cargo.toml"))
        if (root / "go.mod").is_file():
            return ("go", "test", "./...")
        projects = sorted(root.glob("*.csproj"))
        if len(projects) == 1:
            return ("dotnet", "test", str(projects[0]), "--nologo")
        if (root / "pom.xml").is_file():
            return ("mvn", "-B", "test")
        if any((root / name).is_file() for name in ("build.gradle", "build.gradle.kts")):
            return ("gradle", "--no-daemon", "test")
        package = root / "package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                data = {}
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            if isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and scripts["test"].strip():
                return ("npm", "test")
        python_tests = (
            (root / "tests").is_dir()
            or any(root.glob("test_*.py"))
            or any(root.glob("*_test.py"))
        )
        if python_tests:
            return (sys.executable, "-m", "pytest", "-q")
        return None

    def _post_build_test_command(self) -> tuple[str, ...] | None:
        cmake_file = self.workspace / "CMakeLists.txt"
        if not cmake_file.is_file():
            return None
        try:
            source = cmake_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        has_ctest = re.search(
            r"(?im)^\s*(?:enable_testing\s*\(|include\s*\(\s*CTest\b)",
            source,
        )
        if not has_ctest:
            return None
        build_dir = self.workspace / ".vibe-code" / "build" / "cmake"
        return ("ctest", "--test-dir", str(build_dir), "--output-on-failure")

    def _run_command(self, name: str, command: Sequence[str]) -> ValidationStep:
        try:
            result = subprocess.run(
                list(command),
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.test_timeout,
                check=False,
                shell=False,
            )
        except FileNotFoundError:
            return ValidationStep(
                name, False,
                f"Required test runner was not found: {command[0]}",
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return ValidationStep(
                name, False,
                f"Timed out after {self.test_timeout:g}s.\n{str(output)[-MAX_LOG_CHARS:]}",
            )
        output = result.stdout[-MAX_LOG_CHARS:]
        if result.returncode:
            output = (output + f"\nTest command exited with code {result.returncode}.").strip()
        return ValidationStep(name, result.returncode == 0, output or "Command completed.")
