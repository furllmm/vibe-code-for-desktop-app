from __future__ import annotations
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout
from vibe_code.changes import ChangeManager
from .project_edit import ProjectEditProposal, ProjectEditSession

class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    def __init__(self, session, instruction):
        super().__init__()
        self.session, self.instruction = session, instruction
    @Slot()
    def run(self):
        try: self.finished.emit(self.session.propose(self.instruction))
        except Exception as exc: self.failed.emit(str(exc))

class ProjectEditDialog(QDialog):
    def __init__(self, session: ProjectEditSession, manager: ChangeManager, instruction: str, parent=None):
        super().__init__(parent)
        self.session, self.manager, self.proposal = session, manager, None
        self.change_set = None
        self._thread = None
        self.setWindowTitle("Review AI Project Changes")
        self.resize(980, 680)
        layout = QVBoxLayout(self)
        self.status = QLabel("AI is preparing a proposal…")
        layout.addWidget(self.status)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("Apply Project Changes")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        thread = QThread(self)
        worker = _Worker(session, instruction)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._ready)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread, self._worker = thread, worker
        thread.start()

    def _ready(self, proposal):
        if not isinstance(proposal, ProjectEditProposal):
            self._failed("Invalid proposal")
            return
        self.proposal = proposal
        diff = proposal.unified_diff()
        self.preview.setPlainText(diff[:500000] + ("\n[preview truncated]" if len(diff) > 500000 else ""))
        self.status.setText(f"{len(proposal.changes)} file(s) proposed. Review before applying.")
        self.apply_button.setEnabled(True)

    def _failed(self, message):
        self.status.setText(f"Proposal failed: {message}")
        self.preview.setPlainText("No files were changed.")

    def _thread_finished(self):
        if self._thread is not None: self._thread.deleteLater()
        self._thread = None

    def apply_changes(self):
        if self.proposal is None: return
        self.apply_button.setEnabled(False)
        try: self.change_set = self.session.apply(self.proposal, self.manager)
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            QMessageBox.warning(self, "Project changes not applied", str(exc))
            self.apply_button.setEnabled(True)
            return
        super().accept()

    def reject(self):
        if self._thread is not None:
            QMessageBox.information(self, "AI request running", "Wait for the proposal request before closing.")
            return
        super().reject()
