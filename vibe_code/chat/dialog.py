from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from .project_chat import ProjectChatSession


class _ProjectChatWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, session: ProjectChatSession, question: str) -> None:
        super().__init__()
        self.session = session
        self.question = question

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.session.ask(self.question))
        except Exception as exc:
            self.failed.emit(str(exc))


class ProjectChatDialog(QDialog):
    """Asynchronous project-wide chat. It has no file or process tools."""

    def __init__(self, session: ProjectChatSession, workspace_label: str, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self._thread: QThread | None = None
        self._worker: _ProjectChatWorker | None = None
        self.setWindowTitle(f"Chat with Project — {workspace_label}")
        self.resize(820, 640)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Project: {workspace_label} · Relevant files are retrieved for each question."
        ))
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Ask about architecture, functions, bugs, dependencies…")
        layout.addWidget(self.transcript, 1)
        self.question = QPlainTextEdit()
        self.question.setMaximumHeight(100)
        self.question.setPlaceholderText("Ask a question about the whole project…")
        layout.addWidget(self.question)
        actions = QHBoxLayout()
        self.status = QLabel(
            "Read-only chat. Relevant source files may be sent to your configured AI provider."
        )
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
        self.status.setText("Searching project context and asking AI…")

        thread = QThread(self)
        worker = _ProjectChatWorker(self.session, question)
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
            self.status.setText("Wait for the current AI response before closing.")
            return
        super().reject()
