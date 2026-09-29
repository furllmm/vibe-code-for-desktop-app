from __future__ import annotations

import html
import os
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from vibe_code.agent.service import AgentLoop, AgentRequest, AgentRunResult
from vibe_code.agent.worker import AgentWorker
from vibe_code.context.models import ContextRequest
from vibe_code.context.panel import ContextPanel
from vibe_code.context.service import ContextService
from vibe_code.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)
from vibe_code.tools.registry import ToolRegistry
from vibe_code.tools.workspace_tools import ReadFileTool, WriteFileTool
from vibe_code.tools.filesystem import WorkspaceFS
from vibe_code.workspace import Workspace


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vibe Code for Desktop Apps")
        self.resize(1280, 800)
        self.workspace: Workspace | None = None
        self.context_service = ContextService()
        self._thread: QThread | None = None
        self._worker: AgentWorker | None = None

        toolbar = QToolBar("Workspace")
        self.addToolBar(toolbar)
        open_action = QAction("Open Workspace", self)
        open_action.triggered.connect(self.open_workspace)
        refresh_action = QAction("Refresh Context", self)
        refresh_action.triggered.connect(self.refresh_context)
        toolbar.addAction(open_action)
        toolbar.addAction(refresh_action)

        splitter = QSplitter()
        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderLabel("Project")

        chat_splitter = QSplitter()
        chat_splitter.setOrientation(2)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Agent output will appear here…")
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Describe the desktop app or change you want to make…"
        )
        self.run_button = QPushButton("Run Agent")
        self.run_button.clicked.connect(self.run_agent)

        chat_splitter.addWidget(self.output)
        chat_splitter.addWidget(self.prompt)
        chat_splitter.addWidget(self.run_button)
        chat_splitter.setSizes([480, 180, 48])

        self.context_panel = ContextPanel()

        splitter.addWidget(self.project_tree)
        splitter.addWidget(chat_splitter)
        splitter.addWidget(self.context_panel)
        splitter.setSizes([260, 620, 400])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready — open a workspace")

    def open_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open workspace")
        if not selected:
            return
        try:
            self.workspace = Workspace(Path(selected))
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Workspace error: {exc}")
            return

        self.load_workspace(self.workspace.root)
        self.refresh_context()
        self.statusBar().showMessage(f"Workspace: {self.workspace.root}")

    def refresh_context(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return

        prompt = self.prompt.toPlainText().strip() or "project structure and metadata"
        pack = self.context_service.build(
            ContextRequest(prompt, self.workspace.root, token_budget=12000)
        )
        self.context_panel.show_pack(pack)
        self.statusBar().showMessage(f"Context: {pack.summary()}")

    def run_agent(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return

        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self.statusBar().showMessage("Describe the change you want first")
            return
        if self._thread is not None:
            self.statusBar().showMessage("Agent is already running")
            return

        try:
            pack = self.context_service.build(
                ContextRequest(prompt, self.workspace.root, token_budget=12000)
            )
            self.context_panel.show_pack(pack)
            provider = self._build_provider()
            filesystem = WorkspaceFS(self.workspace.root)
            registry = ToolRegistry((
                ReadFileTool(filesystem),
                WriteFileTool(filesystem),
            ))
            loop = AgentLoop(provider, registry)
            request = AgentRequest(prompt, pack)
        except (OSError, ValueError, RuntimeError) as exc:
            self.statusBar().showMessage(f"Agent setup error: {exc}")
            return

        self.output.append(f"<b>You:</b> {html.escape(prompt)}")
        self.run_button.setEnabled(False)
        self.statusBar().showMessage("Agent is working…")

        thread = QThread(self)
        worker = AgentWorker(loop, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._agent_finished)
        worker.failed.connect(self._agent_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._agent_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _build_provider(self) -> OpenAICompatibleProvider:
        base_url = os.environ.get("VIBE_CODE_BASE_URL", "").strip()
        model = os.environ.get("VIBE_CODE_MODEL", "").strip()
        api_key = os.environ.get("VIBE_CODE_API_KEY") or None
        if not base_url or not model:
            raise ValueError(
                "Set VIBE_CODE_BASE_URL and VIBE_CODE_MODEL before running the agent"
            )
        timeout_text = os.environ.get("VIBE_CODE_TIMEOUT", "60").strip()
        try:
            timeout = float(timeout_text)
        except ValueError as exc:
            raise ValueError("VIBE_CODE_TIMEOUT must be a number") from exc
        return OpenAICompatibleProvider(
            OpenAICompatibleConfig(base_url, model, api_key, timeout)
        )

    def _agent_finished(self, result: AgentRunResult) -> None:
        self.output.append(f"<b>Agent:</b> {html.escape(result.content)}")
        if result.executions:
            lines = [
                f"- {execution.name}: {'OK' if execution.result.ok else 'FAILED'}"
                for execution in result.executions
            ]
            self.output.append("<b>Tool calls:</b><br>" + "<br>".join(lines))
        self.statusBar().showMessage(
            f"Agent finished in {result.turns} turn(s)"
            + (" — turn limit reached" if result.stopped_by_limit else "")
        )

    def _agent_failed(self, message: str) -> None:
        self.output.append(f"<b>Agent error:</b> {html.escape(message)}")
        self.statusBar().showMessage(f"Agent error: {message}")

    def _agent_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.run_button.setEnabled(True)

    def load_workspace(self, root: Path) -> None:
        self.project_tree.clear()
        self._add_tree(root, self.project_tree.invisibleRootItem())

    def _add_tree(self, path: Path, parent: QTreeWidgetItem) -> None:
        if path != path.anchor and path.name.startswith("."):
            return
        item = QTreeWidgetItem(parent, [path.name or str(path)])
        if not path.is_dir():
            return
        try:
            children = sorted(
                (
                    child
                    for child in path.iterdir()
                    if child.name not in {".git", ".venv", "__pycache__"}
                ),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return
        for child in children[:500]:
            self._add_tree(child, item)


def run() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
