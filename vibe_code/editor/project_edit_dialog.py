from __future__ import annotations

from collections.abc import Callable
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from vibe_code.changes import ChangeManager, ChangeSet
from vibe_code.runtime.validation import ProjectValidator, ValidationResult
from .project_edit import ProjectEditProposal, ProjectEditSession


class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self.work = work

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.work())
        except Exception as exc:
            self.failed.emit(str(exc))


class ProjectEditDialog(QDialog):
    """Review AI diffs, apply explicitly, and optionally validate a trusted workspace."""

    def __init__(
        self,
        session: ProjectEditSession,
        manager: ChangeManager,
        instruction: str,
        parent=None,
        *,
        validator: ProjectValidator | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.manager = manager
        self.instruction = instruction
        self.validator = validator
        self.proposal: ProjectEditProposal | None = None
        self.change_set: ChangeSet | None = None
        self.applied_change_sets: list[ChangeSet] = []
        self.validation_result: ValidationResult | None = None
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._pending_accept = False

        self.setWindowTitle("Review AI Project Changes")
        self.resize(980, 700)
        layout = QVBoxLayout(self)
        self.status = QLabel(
            "AI is preparing a proposal. Full contents of selected project files "
            "may be sent to your configured provider."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.preview, 1)

        self.trust = QCheckBox(
            "I trust this workspace and allow its tests, build scripts and preview code to execute."
        )
        self.trust.setEnabled(validator is not None)
        layout.addWidget(self.trust)
        if validator is None:
            self.status.setText(
                "No supported preview adapter was detected. Changes can still be reviewed "
                "and applied, but automatic validation is unavailable."
            )

        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply Changes")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_changes)
        actions.addWidget(self.apply_button)

        self.validate_button = QPushButton("Apply & Validate")
        self.validate_button.setEnabled(False)
        self.validate_button.setToolTip(
            "Run detected project tests, build the app, then check preview startup."
        )
        self.validate_button.clicked.connect(self.apply_and_validate)
        self.validate_button.setEnabled(validator is not None)
        actions.addWidget(self.validate_button)

        self.repair_button = QPushButton("Ask AI for Fix")
        self.repair_button.setEnabled(False)
        self.repair_button.clicked.connect(self.ask_ai_for_fix)
        actions.addWidget(self.repair_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        self._start_task(
            lambda: self.session.propose(self.instruction),
            self._proposal_ready,
            "Preparing initial proposal…",
        )

    def _start_task(
        self,
        work: Callable[[], object],
        on_success: Callable[[object], None],
        status: str,
    ) -> None:
        if self._thread is not None:
            return
        self.status.setText(status)
        self._set_actions_enabled(False)
        thread = QThread(self)
        worker = _Worker(work)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_success)
        worker.failed.connect(self._task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread, self._worker = thread, worker
        thread.start()

    def _set_actions_enabled(self, enabled: bool) -> None:
        has_proposal = self.proposal is not None
        self.apply_button.setEnabled(enabled and has_proposal)
        self.validate_button.setEnabled(
            enabled and has_proposal and self.validator is not None
        )
        self.repair_button.setEnabled(
            enabled and self.validation_result is not None
            and not self.validation_result.success
        )
        self.close_button.setEnabled(enabled)

    def _proposal_ready(self, value: object) -> None:
        if not isinstance(value, ProjectEditProposal):
            self._task_failed("AI returned an invalid project edit proposal.")
            return
        self.proposal = value
        diff = value.unified_diff()
        self.preview.setPlainText(
            diff[:500000] + ("\n[preview truncated]" if len(diff) > 500000 else "")
        )
        self.status.setText(
            f"{len(value.changes)} file(s) proposed. Review the diff before applying."
        )
        self._set_actions_enabled(True)

    def _validation_ready(self, value: object) -> None:
        if not isinstance(value, ValidationResult):
            self._task_failed("Validation returned an unexpected result.")
            return
        self.validation_result = value
        self.preview.setPlainText(value.output or "Validation produced no output.")
        if value.success:
            self.status.setText("Tests/build/preview validation succeeded.")
            self._pending_accept = True
            return
        self.status.setText(
            "Validation failed. The accepted changes are still in place. "
            "Ask AI for a repair proposal, review its diff, then apply and validate again."
        )
        self.proposal = None
        self._set_actions_enabled(True)

    def _task_failed(self, message: str) -> None:
        self.status.setText(f"Operation failed: {message}")
        self.preview.setPlainText("No additional file changes were made by this operation.")
        self._set_actions_enabled(True)

    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._set_actions_enabled(True)
        if self._pending_accept:
            self._pending_accept = False
            super().accept()

    def _apply_current_proposal(self) -> bool:
        if self.proposal is None:
            return False
        try:
            change_set = self.session.apply(self.proposal, self.manager)
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            QMessageBox.warning(self, "Project changes not applied", str(exc))
            return False
        self.change_set = change_set
        self.applied_change_sets.append(change_set)
        self.proposal = None
        return True

    def apply_changes(self) -> None:
        if self._thread is not None or not self._apply_current_proposal():
            return
        super().accept()

    def apply_and_validate(self) -> None:
        if self.validator is None or self._thread is not None:
            return
        if not self.trust.isChecked():
            QMessageBox.warning(
                self,
                "Workspace trust required",
                "Tests, build tools and preview applications can execute project-controlled code. "
                "Review this workspace and confirm trust before validation.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Run project validation?",
            "This will run the detected test command, build the project and start its preview. "
            "Project test/build scripts may execute arbitrary code. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._apply_current_proposal():
            return
        self._start_task(
            self.validator.run,
            self._validation_ready,
            "Running project tests, build and preview smoke check…",
        )

    def ask_ai_for_fix(self) -> None:
        if (
            self._thread is not None
            or self.validation_result is None
            or self.validation_result.success
        ):
            return
        diagnostics = self.validation_result.output[-24000:]
        repair_instruction = (
            "The latest accepted project changes failed validation. Propose the smallest "
            "maintainable code repair for the current workspace. Do not claim to have run "
            "tests or changed files. Validation diagnostics follow:\n\n"
            f"<validation_diagnostics>\n{diagnostics}\n</validation_diagnostics>"
        )
        self.validation_result = None
        self._start_task(
            lambda: self.session.propose(repair_instruction),
            self._proposal_ready,
            "Asking AI for a repair proposal…",
        )

    def reject(self) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self, "Operation running",
                "Wait for the current AI or validation operation before closing.",
            )
            return
        super().reject()
