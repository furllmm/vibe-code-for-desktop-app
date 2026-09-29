from __future__ import annotations

import html
import os
import shlex
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer
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
    QTabWidget,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
)

from vibe_code.agent.service import AgentLoop, AgentRequest, AgentRunResult
from vibe_code.agent.orchestrator import AgentOrchestrator, OrchestrationResult, PreviewFailure, RepairResult
from vibe_code.agent.recovery import RecoveryAction, RecoveryDecision
from vibe_code.agent.worker import AgentWorker
from vibe_code.context.models import ContextRequest
from vibe_code.context.panel import ContextPanel
from vibe_code.context.service import ContextService
from vibe_code.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)
from vibe_code.tools.registry import ToolRegistry
from vibe_code.tools.change_tools import GetChangesTool, RollbackChangesTool
from vibe_code.tools.workspace_tools import ReadFileTool, WriteFileTool
from vibe_code.tools.preview_tools import GetPreviewLogsTool, RunPreviewTool, StopPreviewTool
from vibe_code.tools.filesystem import WorkspaceFS
from vibe_code.changes import ChangeManager
from vibe_code.changes.panel import ChangePanel
from vibe_code.workspace import Workspace
from vibe_code.runtime import GenericPreviewAdapter, PreviewConfig, PreviewEngine, PythonPySide6Adapter


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vibe Code for Desktop Apps")
        self.resize(1280, 800)
        self.workspace: Workspace | None = None
        self.context_service = ContextService()
        self._thread: QThread | None = None
        self._worker: AgentWorker | None = None
        self._preview: PreviewEngine | None = None
        self._change_manager: ChangeManager | None = None
        self._orchestrator: AgentOrchestrator | None = None
        self._last_failure: PreviewFailure | None = None
        self._pending_recovery_failure: PreviewFailure | None = None

        toolbar = QToolBar("Workspace")
        self.addToolBar(toolbar)
        open_action = QAction("Open Workspace", self)
        open_action.triggered.connect(self.open_workspace)
        refresh_action = QAction("Refresh Context", self)
        refresh_action.triggered.connect(self.refresh_context)
        toolbar.addAction(open_action)
        toolbar.addAction(refresh_action)
        preview_start = QAction("Run Preview", self)
        preview_start.triggered.connect(self.run_preview)
        preview_stop = QAction("Stop Preview", self)
        preview_stop.triggered.connect(self.stop_preview)
        toolbar.addAction(preview_start)
        toolbar.addAction(preview_stop)
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._poll_preview)

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
        self.change_panel: ChangePanel | None = None

        splitter.addWidget(self.project_tree)
        splitter.addWidget(chat_splitter)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.context_panel, "Context")
        splitter.addWidget(self.right_tabs)
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

    def run_preview(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        command_text = os.environ.get("VIBE_CODE_PREVIEW_COMMAND", "").strip()
        try:
            if command_text:
                command = tuple(shlex.split(command_text))
                if not command:
                    raise ValueError("VIBE_CODE_PREVIEW_COMMAND must not be empty")
                adapter = GenericPreviewAdapter(PreviewConfig(command))
                adapter_name = "configured command"
            else:
                entrypoint = os.environ.get("VIBE_CODE_PYTHON_ENTRYPOINT") or None
                adapter = PythonPySide6Adapter(entrypoint)
                adapter_name = "Python/PySide6"
                if not adapter.detect(self.workspace.root):
                    raise RuntimeError(
                        "No PySide6 project detected. Set VIBE_CODE_PREVIEW_COMMAND "
                        "or add a Python/PySide6 project."
                    )
            self._preview = PreviewEngine(
                self.workspace.root,
                adapter,
            )
            self._preview.build()
            self._preview.start()
            self._preview_timer.start()
            self.statusBar().showMessage(f"Preview is running ({adapter_name})")
        except (OSError, ValueError, RuntimeError) as exc:
            self._preview = None
            self.statusBar().showMessage(f"Preview error: {exc}")

    def stop_preview(self) -> None:
        if self._preview is None:
            return
        result = self._preview.process.stop()
        self._preview_timer.stop()
        self._preview = None
        if result is not None:
            self.statusBar().showMessage(
                f"Preview stopped (exit {result.returncode})"
            )

    def _poll_preview(self) -> None:
        if self._preview is None:
            self._preview_timer.stop()
            return
        logs = self._preview.read_logs()
        if logs:
            self.output.append(
                "<b>Preview:</b> " + html.escape(logs).replace("\n", "<br>")
            )
        result = self._preview.poll()
        if result is not None:
            self._preview_timer.stop()
            self.output.append(
                f"<b>Preview exited:</b> {result.returncode}"
                + (" (crash/error)" if result.crashed else "")
            )
            self.statusBar().showMessage(
                f"Preview exited with code {result.returncode}"
            )
            self._preview = None

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
            if self._preview is not None:
                self.stop_preview()
            pack = self.context_service.build(
                ContextRequest(prompt, self.workspace.root, token_budget=12000)
            )
            self.context_panel.show_pack(pack)
            provider = self._build_provider()
            filesystem = WorkspaceFS(self.workspace.root)
            changes = ChangeManager(filesystem)
            self._change_manager = changes
            if self.change_panel is None:
                self.change_panel = ChangePanel(changes)
                self.change_panel.rollback_requested.connect(self._rollback_change)
                self.right_tabs.addTab(self.change_panel, "Changes")
            self.change_panel.refresh()
            tools = [
                ReadFileTool(filesystem),
                WriteFileTool(filesystem, changes),
                GetChangesTool(changes),
                RollbackChangesTool(changes),
            ]
            preview = self._build_preview_engine()
            registry = ToolRegistry(tuple(tools))
            loop = AgentLoop(provider, registry)
            request = AgentRequest(prompt, pack)
            self._orchestrator = None
            if preview is not None:
                self._preview = preview
                self._orchestrator = AgentOrchestrator(
                    loop,
                    self.context_service,
                    changes,
                    preview,
                    self.workspace.root,
                    max_repair_cycles=3,
                )
        except (OSError, ValueError, RuntimeError) as exc:
            self.statusBar().showMessage(f"Agent setup error: {exc}")
            return

        self.output.append(f"<b>You:</b> {html.escape(prompt)}")
        self.run_button.setEnabled(False)
        self.statusBar().showMessage("Agent is working…")

        thread = QThread(self)
        work = self._orchestrator.run if self._orchestrator is not None else None
        worker = AgentWorker(loop, request, work=(lambda: work(prompt)) if work is not None else None)
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

    def _build_preview_engine(self) -> PreviewEngine | None:
        if self.workspace is None:
            return None
        command_text = os.environ.get("VIBE_CODE_PREVIEW_COMMAND", "").strip()
        if command_text:
            command = tuple(shlex.split(command_text))
            if not command:
                raise ValueError("VIBE_CODE_PREVIEW_COMMAND must not be empty")
            adapter = GenericPreviewAdapter(PreviewConfig(command))
        else:
            entrypoint = os.environ.get("VIBE_CODE_PYTHON_ENTRYPOINT") or None
            adapter = PythonPySide6Adapter(entrypoint)
            if not adapter.detect(self.workspace.root):
                return None
        return PreviewEngine(self.workspace.root, adapter)
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

    def _agent_finished(self, result: object) -> None:
        if isinstance(result, OrchestrationResult):
            agent = result.agent
            self.output.append(f"<b>Agent:</b> {html.escape(agent.content)}")
            self._last_failure = result.failure
            if self.change_panel is not None:
                self.change_panel.refresh()
            self.statusBar().showMessage(
                f"Agent finished in {agent.turns} turn(s)"
                + (" — turn limit reached" if agent.stopped_by_limit else "")
            )
            if result.failure is not None:
                self._handle_preview_failure(result.failure)
            else:
                self._preview_timer.start()
                self.output.append("<b>Preview:</b> started successfully.")
            return

        if not isinstance(result, AgentRunResult):
            self.output.append(f"<b>Agent:</b> {html.escape(str(result))}")
            return

        self.output.append(f"<b>Agent:</b> {html.escape(result.content)}")
        if self.change_panel is not None:
            self.change_panel.refresh()
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

    def _handle_preview_failure(self, failure: PreviewFailure) -> None:
        logs = failure.logs.strip() or "<no captured preview output>"
        preview = logs[-4000:]
        box = QMessageBox(self)
        box.setWindowTitle("Preview crashed")
        box.setText(
            f"Preview crashed with exit code {failure.returncode}. "
            "Choose how to recover."
        )
        box.setInformativeText(preview)
        fix = box.addButton("Fix", QMessageBox.ButtonRole.AcceptRole)
        revert = box.addButton("Revert Changes", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Keep Changes", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is fix:
            action = RecoveryAction.FIX
        elif clicked is revert:
            action = RecoveryAction.REVERT
        else:
            action = RecoveryAction.KEEP
        self._apply_recovery_decision(
            RecoveryDecision(action, failure.cycle, failure.change_ids)
        )

    def _apply_recovery_decision(self, decision: RecoveryDecision) -> None:
        failure = self._last_failure
        if failure is None:
            return
        if decision.action is RecoveryAction.FIX:
            self._start_repair(failure)
        elif decision.action is RecoveryAction.REVERT:
            self._revert_failure(failure)
        else:
            self._last_failure = None
            self.statusBar().showMessage("Preview failure acknowledged; changes kept.")

    def _start_repair(self, failure: PreviewFailure) -> None:
        if self._orchestrator is None or self._thread is not None:
            return
        loop = self._orchestrator.agent
        request = AgentRequest("repair preview failure", self.context_service.build(
            ContextRequest("repair preview failure", self.workspace.root, token_budget=12000)
        ))
        self.output.append("<b>Recovery:</b> fixing preview crash…")
        self.run_button.setEnabled(False)
        thread = QThread(self)
        worker = AgentWorker(
            loop,
            request,
            work=lambda: self._orchestrator.repair(failure),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._repair_finished)
        worker.failed.connect(self._agent_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._agent_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _repair_finished(self, result: object) -> None:
        if not isinstance(result, RepairResult):
            self._agent_finished(result)
            return
        if self.change_panel is not None:
            self.change_panel.refresh()
        self._last_failure = result.attempts[-1].failure if result.attempts else None
        if result.success:
            self.output.append(
                f"<b>Recovery:</b> preview recovered after {len(result.attempts)} repair attempt(s)."
            )
            self._preview_timer.start()
            self.statusBar().showMessage("Preview recovered.")
        elif self._last_failure is not None:
            self.output.append("<b>Recovery:</b> repair limit reached; preview still crashes.")
            self._pending_recovery_failure = self._last_failure
        else:
            self.statusBar().showMessage("Recovery stopped without a preview result.")

    def _revert_failure(self, failure: PreviewFailure) -> None:
        if self._change_manager is None:
            return
        try:
            self._change_manager.rollback_many(failure.change_ids)
        except (OSError, KeyError, PermissionError, RuntimeError) as exc:
            QMessageBox.warning(self, "Rollback failed", str(exc))
            return
        if self.workspace is not None:
            self.load_workspace(self.workspace.root)
            self.refresh_context()
        if self.change_panel is not None:
            self.change_panel.refresh()
        self._last_failure = None
        self.statusBar().showMessage("Failed changes reverted safely.")

    def _rollback_change(self, change_id: str) -> None:
        if self._change_manager is None:
            return
        answer = QMessageBox.question(
            self,
            "Revert change?",
            f"Revert change {change_id[:12]}? This restores the recorded file state.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            change_set = self._change_manager.rollback(change_id)
        except (OSError, KeyError, PermissionError, RuntimeError) as exc:
            QMessageBox.warning(self, "Rollback failed", str(exc))
            return
        paths = ", ".join(item.path for item in change_set.changes)
        self.output.append(f"<b>Reverted:</b> {html.escape(paths)}")
        if self.workspace is not None:
            self.load_workspace(self.workspace.root)
            self.refresh_context()
        if self.change_panel is not None:
            self.change_panel.refresh()

    def _agent_failed(self, message: str) -> None:
        self.output.append(f"<b>Agent error:</b> {html.escape(message)}")
        self.statusBar().showMessage(f"Agent error: {message}")

    def _agent_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.run_button.setEnabled(True)
        failure = self._pending_recovery_failure
        self._pending_recovery_failure = None
        if failure is not None:
            QTimer.singleShot(0, lambda: self._handle_preview_failure(failure))

    def closeEvent(self, event) -> None:
        self.stop_preview()
        super().closeEvent(event)

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
