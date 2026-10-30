from __future__ import annotations

import subprocess
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

    def execute(
        self,
        plan: PackagingPlan,
        *,
        trusted_workspace: bool = False,
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
        try:
            result = subprocess.run(
                list(plan.command),
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=plan.timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Packaging tool not found: {plan.command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return PackagingResult(
                False, f"Packaging timed out after {plan.timeout_seconds}s.\n{str(output)[-12000:]}",
                plan.output_dir, None,
            )
        return PackagingResult(
            result.returncode == 0,
            result.stdout[-12000:],
            plan.output_dir,
            result.returncode,
        )
