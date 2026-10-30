from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from vibe_code.editor.selection_chat import SelectionChatSession


class _ChatWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, session: SelectionChatSession, question: str) -> None:
        super().__init__()
        self.session = session
        self.question = question

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.session.ask(self.question))
        except Exception as exc:
            self.failed.emit(str(exc))


class SelectionChatDialog(QDialog):
    """Asynchronous, read-only chat bound to the selected source snapshot."""

    def __init__(
        self, session: SelectionChatSession, relative_path: str, parent=None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._thread: QThread | None = None
        self._worker: _ChatWorker | None = None
        self.setWindowTitle(f"Ask AI about Selection — {relative_path}")
        self.resize(760, 600)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Frozen source context: {relative_path}"))
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Ask follow-up questions about the selected code…")
        layout.addWidget(self.transcript, 1)
        self.question = QPlainTextEdit()
        self.question.setMaximumHeight(100)
        self.question.setPlaceholderText("Ask a question about this code…")
        layout.addWidget(self.question)
        actions = QHBoxLayout()
        self.status = QLabel("Read-only conversation — no files are changed.")
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_question)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.status, 1)
        actions.addWidget(self.send_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

    def send_question(self) -> None:
        if self._thread is not None:
            return
        question = self.question.toPlainText().strip()
        if not question:
            self.status.setText("Enter a question first.")
            return
        self.question.clear()
        self.transcript.appendPlainText(f"You: {question}\n")
        self.send_button.setEnabled(False)
        self.status.setText("AI is thinking…")

        thread = QThread(self)
        worker = _ChatWorker(self.session, question)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._answer_received)
        worker.failed.connect(self._answer_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread, self._worker = thread, worker
        thread.start()

    def _answer_received(self, answer: str) -> None:
        self.transcript.appendPlainText(f"AI: {answer}\n")
        self.status.setText("Ready")

    def _answer_failed(self, message: str) -> None:
        self.transcript.appendPlainText(f"AI error: {message}\n")
        self.status.setText("Request failed — you can try again.")

    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.send_button.setEnabled(True)

    def reject(self) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self, "AI request running",
                "Wait for the current AI response before closing this conversation.",
            )
            return
        super().reject()
