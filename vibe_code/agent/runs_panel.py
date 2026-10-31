from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .autonomy import AutonomousRunner, CheckpointStore, RunCheckpoint
from .background import BackgroundTaskManager, DuplicateTaskError

RunnerFactory = Callable[[bool, object, object], AutonomousRunner]


class RunsPanel(QWidget):
    """Start Continue / Full Do runs in the background and monitor, cancel or resume them."""

    def __init__(self, manager: BackgroundTaskManager, factory: RunnerFactory) -> None:
        super().__init__()
        self.manager = manager
        self.factory = factory
        self.workspace: Path | None = None
        self.default_goal: Callable[[], str] = lambda: ""

        self.mode = QComboBox()
        self.mode.addItem("Full Do — analyse and complete the whole project", "full_do")
        self.mode.addItem("Continue — resume the saved task", "continue")
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("Goal (optional for Full Do; defaults to the saved task for Continue)")
        self.validate = QCheckBox("Run project tests/build after each task (I trust this workspace)")
        self.start_button = QPushButton("Run in Background")
        self.start_button.clicked.connect(self.start_run)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.resume_button = QPushButton("Resume")
        self.resume_button.clicked.connect(self.resume_selected)
        buttons = QHBoxLayout()
        for button in (self.start_button, self.cancel_button, self.resume_button):
            buttons.addWidget(button)

        self.runs = QTreeWidget()
        self.runs.setHeaderLabels(["Run", "Mode", "Status", "Current task", "Tasks"])
        self.runs.itemSelectionChanged.connect(self._show_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.status = QLabel("Open a workspace to start autonomous runs")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.mode)
        layout.addWidget(self.goal)
        layout.addWidget(self.validate)
        layout.addLayout(buttons)
        layout.addWidget(self.runs, 2)
        layout.addWidget(self.details, 3)
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    # ------------------------------------------------------------------ actions
    def set_workspace(self, workspace: Path | None) -> None:
        self.workspace = workspace
        self.refresh()
        if workspace is not None:
            resumable = CheckpointStore(workspace).latest_resumable()
            if resumable is not None and self.manager.get(self._key(workspace, resumable.run_id)) is None:
                self.status.setText(f"Interrupted run {resumable.run_id} can be resumed: {resumable.summary()}")

    def start_run(self) -> None:
        if self.workspace is None:
            self.status.setText("Open a workspace first")
            return
        mode = self.mode.currentData()
        goal = self.goal.text().strip() or (self.default_goal() if mode == "continue" else "")
        if mode == "continue" and not goal:
            self.status.setText("No saved task to continue; enter a goal")
            return
        digest = hashlib.sha256(f"{mode}\n{goal}".encode()).hexdigest()[:10]
        run_id = f"{mode}-{digest}"
        self._submit(run_id, f"{mode}: {goal[:40] or 'whole project'}",
                     lambda runner: runner.start(mode, goal, run_id=run_id))

    def resume_selected(self) -> None:
        run_id = self._selected_run()
        if run_id is None or self.workspace is None:
            self.status.setText("Select a stopped or interrupted run")
            return
        self._submit(run_id, f"resume {run_id}", lambda runner: runner.resume(run_id))

    def cancel_selected(self) -> None:
        run_id = self._selected_run()
        if run_id is not None and self.workspace is not None and self.manager.cancel(self._key(self.workspace, run_id)):
            self.status.setText(f"Cancelling {run_id} after the current step…")

    def _submit(self, run_id: str, label: str, call) -> None:
        validate = self.validate.isChecked()

        def work(cancel_event, progress) -> RunCheckpoint:
            return call(self.factory(validate, cancel_event, progress))

        try:
            self.manager.submit(self._key(self.workspace, run_id), label, work)
        except DuplicateTaskError as exc:
            QMessageBox.information(self, "Already running", str(exc))
            return
        self.status.setText(f"Started {label} in the background")
        self.refresh()

    # ------------------------------------------------------------------ display
    @staticmethod
    def _key(workspace: Path, run_id: str) -> str:
        return f"{workspace}::{run_id}"

    def _selected_run(self) -> str | None:
        items = self.runs.selectedItems()
        return items[0].text(0) if items else None

    def _checkpoints(self) -> dict[str, tuple[RunCheckpoint | None, str]]:
        result: dict[str, tuple[RunCheckpoint | None, str]] = {}
        if self.workspace is None:
            return result
        store = CheckpointStore(self.workspace)
        for run_id in store.list_runs()[:50]:
            try:
                checkpoint = store.load(run_id)
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                result[run_id] = (None, f"corrupted: {exc}")
                continue
            status = checkpoint.status
            job = self.manager.get(self._key(self.workspace, run_id))
            if status == "running" and (job is None or not job.active):
                status = "interrupted"
            result[run_id] = (checkpoint, status)
        for job in self.manager.jobs():
            if job.key.startswith(f"{self.workspace}::"):
                run_id = job.key.split("::", 1)[1]
                if job.progress is not None:
                    result[run_id] = (job.progress, job.status if not job.active else job.progress.status)
                elif job.status == "error":
                    result[run_id] = (result.get(run_id, (None, ""))[0], f"error: {job.error}")
                elif run_id not in result:
                    result[run_id] = (None, job.status)
        return result

    def refresh(self) -> None:
        selected = self._selected_run()
        rows = self._checkpoints()
        self.runs.clear()
        for run_id, (checkpoint, status) in rows.items():
            current = checkpoint.current_task() if checkpoint else None
            counts = checkpoint.counts() if checkpoint else {}
            done = sum(v for k, v in counts.items() if k not in {"pending", "running"})
            row = QTreeWidgetItem([
                run_id,
                checkpoint.mode if checkpoint else "",
                status,
                current.title if current and status in {"running", "interrupted", "stopped"} else "",
                f"{done}/{len(checkpoint.tasks)}" if checkpoint else "",
            ])
            self.runs.addTopLevelItem(row)
            if run_id == selected:
                row.setSelected(True)
        self._show_details()

    def _show_details(self) -> None:
        run_id = self._selected_run()
        entry = self._checkpoints().get(run_id) if run_id else None
        if not entry or entry[0] is None:
            self.details.setPlainText(entry[1] if entry else "")
            return
        checkpoint = entry[0]
        lines = [checkpoint.summary(), f"Goal: {checkpoint.goal}",
                 f"Iterations: {checkpoint.iterations}  Tokens: ~{checkpoint.tokens_used}  "
                 f"Elapsed: {checkpoint.elapsed_seconds:.0f}s", "", "Tasks:"]
        lines += [f"  [{t.status}] {t.id} {t.title} (attempts {t.attempts})" for t in checkpoint.tasks]
        lines += ["", "Log:"] + [f"  {line}" for line in checkpoint.log[-40:]]
        self.details.setPlainText("\n".join(lines))
