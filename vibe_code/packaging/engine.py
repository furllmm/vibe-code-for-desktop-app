from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .adapters import PackagingRegistry
from .models import PackageRequest, PackagingPlan, PackagingResult


class PackagingEngine:
    """Plan and execute explicit packaging commands for a trusted workspace."""

    def __init__(self, workspace: Path, registry: PackagingRegistry | None = None) -> None:
        self.workspace = workspace.resolve()
        self.registry = registry or PackagingRegistry()
        self._issued_plans: set[PackagingPlan] = set()

    def create_plan(self, request: PackageRequest) -> PackagingPlan:
        plan = self.registry.create_plan(self.workspace, request)
        output = plan.output_dir.resolve()
        if output != self.workspace and self.workspace not in output.parents:
            raise ValueError("Package output must stay inside the workspace")
        self._issued_plans.add(plan)
        return plan

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                process.kill()
            process.wait()

    def execute(
        self,
        plan: PackagingPlan,
        *,
        trusted_workspace: bool = False,
        cancel_event: threading.Event | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> PackagingResult:
        if plan not in self._issued_plans:
            raise ValueError("Packaging plan was not created by this engine")
        if not trusted_workspace:
            raise PermissionError(
                "Packaging can execute project-controlled build hooks. "
                "Explicitly trust this workspace before running it."
            )
        if not plan.command or not plan.output_dir.is_absolute():
            raise ValueError("Invalid packaging plan")

        plan.output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        captured = ""
        offset = 0
        try:
            with tempfile.TemporaryFile(mode="w+b") as output:
                kwargs: dict[str, object] = {}
                if os.name == "nt":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    kwargs["start_new_session"] = True
                try:
                    process = subprocess.Popen(
                        list(plan.command),
                        cwd=self.workspace,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        shell=False,
                        **kwargs,
                    )
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        f"Packaging tool not found: {plan.command[0]}"
                    ) from exc

                cancelled = False
                timed_out = False
                while process.poll() is None:
                    output.flush()
                    output.seek(offset)
                    chunk = output.read()
                    offset += len(chunk)
                    if chunk:
                        decoded = chunk.decode("utf-8", errors="replace")
                        captured = (captured + decoded)[-12000:]
                        if on_output is not None:
                            on_output(decoded)
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        self._stop_process(process)
                        break
                    if time.monotonic() - started >= plan.timeout_seconds:
                        timed_out = True
                        self._stop_process(process)
                        break
                    time.sleep(0.1)

                output.flush()
                output.seek(offset)
                chunk = output.read()
                if chunk:
                    decoded = chunk.decode("utf-8", errors="replace")
                    captured = (captured + decoded)[-12000:]
                    if on_output is not None:
                        on_output(decoded)

                if cancelled:
                    return PackagingResult(
                        False, "Packaging cancelled.\\n" + captured,
                        plan.output_dir, process.returncode,
                    )
                if timed_out:
                    return PackagingResult(
                        False,
                        f"Packaging timed out after {plan.timeout_seconds}s.\\n{captured}",
                        plan.output_dir,
                        process.returncode,
                    )
                return PackagingResult(
                    process.returncode == 0, captured,
                    plan.output_dir, process.returncode,
                )
        except OSError as exc:
            raise RuntimeError(f"Could not run packaging command: {exc}") from exc
