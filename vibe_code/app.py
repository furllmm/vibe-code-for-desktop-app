from __future__ import annotations

import html
import os
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QHBoxLayout,
    QWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolBar,
    QTabWidget,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
)

from vibe_code.agent.service import AgentLoop, AgentRequest, AgentRunResult
from vibe_code.agent.enhance import EnhancementService
from vibe_code.agent.task_state import TaskState, TaskStateStore
from vibe_code.agent.orchestrator import AgentOrchestrator, OrchestrationResult, PreviewFailure, RepairResult
from vibe_code.agent.recovery import RecoveryAction, RecoveryDecision
from vibe_code.agent.worker import AgentWorker
from vibe_code.context.models import ContextItem, ContextPack, ContextRequest
from vibe_code.context.panel import ContextPanel
from vibe_code.context.service import ContextService
from vibe_code.skills.service import SkillService
from vibe_code.templates.service import TemplateService, TemplateError
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
from vibe_code.runtime import PreviewEngine, detect_preview_adapter


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vibe Code for Desktop Apps")
        self.resize(1280, 800)
        self.workspace: Workspace | None = None
        self.context_service = ContextService()
        self.skill_service = SkillService()
        self.template_service = TemplateService()
        self._resume_requested = False
        self._task_original_prompt = ""
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
        templates_action = QAction("Templates…", self)
        templates_action.triggered.connect(self.open_template_picker)
        toolbar.addAction(templates_action)
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
        self.enhance_button = QPushButton("Enhance")
        self.enhance_button.setToolTip(
            "Turn your rough request into a detailed, project-aware brief for review."
        )
        self.enhance_button.clicked.connect(self.enhance_prompt)
        self.continue_button = QPushButton("Continue")
        self.continue_button.setToolTip(
            "Resume the last saved task after inspecting current files and changes."
        )
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_task)
        action_row = QWidget()
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(self.enhance_button)
        action_layout.addWidget(self.continue_button)
        action_layout.addWidget(self.run_button)

        chat_splitter.addWidget(self.output)
        chat_splitter.addWidget(self.prompt)
        chat_splitter.addWidget(action_row)
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
        self._refresh_continue_state()
        self.refresh_context()
        self.statusBar().showMessage(f"Workspace: {self.workspace.root}")

    def open_template_picker(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace before choosing a template")
            return
        try:
            templates = self.template_service.list_templates()
        except (OSError, ValueError, TemplateError) as exc:
            QMessageBox.warning(self, "Templates unavailable", str(exc))
            return
        if not templates:
            QMessageBox.information(self, "Templates", "No valid templates were found.")
            return

        choices = [f"{item['name']} — {item['description']}" for item in templates]
        selected, accepted = QInputDialog.getItem(
            self, "Template picker", "Template:", choices, 0, False
        )
        if not accepted:
            return
        template = templates[choices.index(selected)]
        try:
            plan = self.template_service.plan(template["id"], self.workspace.root)
        except (OSError, ValueError, TemplateError) as exc:
            QMessageBox.warning(self, "Template preview failed", str(exc))
            return

        existing = [item.path for item in plan.files if item.exists]
        new_files = [item.path for item in plan.files if not item.exists]
        preview = (
            f"Template: {template['name']}\n\n"
            f"New files ({len(new_files)}):\n"
            + ("\n".join(f"  + {path}" for path in new_files) or "  (none)")
            + "\n\nExisting files that will be skipped by default "
            f"({len(existing)}):\n"
            + ("\n".join(f"  • {path}" for path in existing) or "  (none)")
            + "\n\nNo files are changed until you approve the next step."
        )
        preview_box = QMessageBox(self)
        preview_box.setWindowTitle("Review template changes")
        preview_box.setIcon(QMessageBox.Icon.Information)
        preview_box.setText("Template application preview")
        preview_box.setInformativeText(preview)
        apply_button = preview_box.addButton(
            "Apply New Files", QMessageBox.ButtonRole.AcceptRole
        )
        preview_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        preview_box.exec()
        if preview_box.clickedButton() is not apply_button:
            return

        try:
            result = self.template_service.apply(
                template["id"], self.workspace.root, overwrite=False
            )
        except (OSError, ValueError, TemplateError) as exc:
            QMessageBox.warning(self, "Template application failed", str(exc))
            return
        self.load_workspace(self.workspace.root)
        self.refresh_context()
        created = "\n".join(result["created"]) or "(no new files created)"
        skipped = "\n".join(result["skipped"])
        message = f"Created files:\n{created}"
        if skipped:
            message += f"\n\nSkipped existing files (not overwritten):\n{skipped}"
        QMessageBox.information(self, "Template applied", message)
        self.statusBar().showMessage(
            f"Template applied: {len(result['created'])} created, "
            f"{len(result['skipped'])} skipped"
        )

    def refresh_context(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return

        prompt = self.prompt.toPlainText().strip() or "project structure and metadata"
        pack = self._build_context(prompt)
        self.context_panel.show_pack(pack)
        self.statusBar().showMessage(f"Context: {pack.summary()}")


    def _build_context(self, prompt: str) -> ContextPack:
        if self.workspace is None:
            raise ValueError("Open a workspace first")
        pack = self.context_service.build(
            ContextRequest(prompt, self.workspace.root, token_budget=12000)
        )
        skills = self.skill_service.load_for_prompt(self.workspace.root, prompt)
        if not skills:
            return pack
        skill_items = tuple(
            ContextItem(
                path=skill.path,
                kind="metadata",
                score=float(skill.score),
                reason=f"relevant skill: {skill.name}",
                content=skill.content,
            )
            for skill in skills
        )
        skill_tokens = sum(len(item.content or "") for item in skill_items) // 4
        return ContextPack(
            items=pack.items + skill_items,
            estimated_tokens=pack.estimated_tokens + skill_tokens,
        )

    def _task_store(self) -> TaskStateStore | None:
        return TaskStateStore(self.workspace.root) if self.workspace is not None else None

    def _refresh_continue_state(self) -> None:
        store = self._task_store()
        if store is None:
            self.continue_button.setEnabled(False)
            return
        try:
            self.continue_button.setEnabled(store.load() is not None)
        except RuntimeError as exc:
            self.continue_button.setEnabled(False)
            self.statusBar().showMessage(str(exc))

    def continue_task(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        if self._thread is not None:
            self.statusBar().showMessage("Another agent task is already running")
            return
        store = self._task_store()
        if store is None:
            return
        try:
            state = store.load()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Continue unavailable", str(exc))
            return
        if state is None:
            self.statusBar().showMessage("No saved task is available to continue")
            self._refresh_continue_state()
            return
        self._resume_requested = True
        self._task_original_prompt = state.original_prompt
        self.prompt.setPlainText(state.continuation_prompt())
        self.statusBar().showMessage("Resume brief loaded. Review it, then press Run Agent.")

    def run_preview(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        try:
            adapter = detect_preview_adapter(self.workspace.root)
            if adapter is None:
                raise RuntimeError(
                    "No supported desktop project detected. "
                    "Set VIBE_CODE_PREVIEW_COMMAND for a custom command."
                )
            self._preview = PreviewEngine(self.workspace.root, adapter)
            self._preview.build()
            self._preview.start()
            self._preview_timer.start()
            self.statusBar().showMessage(
                f"Preview is running ({type(adapter).__name__})"
            )
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


    def enhance_prompt(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self.statusBar().showMessage("Describe your idea before enhancing it")
            return
        if self._thread is not None:
            self.statusBar().showMessage("Another agent task is already running")
            return
        try:
            pack = self._build_context(prompt)
            self.context_panel.show_pack(pack)
            provider = self._build_provider()
        except (OSError, ValueError, RuntimeError) as exc:
            self.statusBar().showMessage(f"Enhance setup error: {exc}")
            return

        self.output.append(f"<b>Enhance request:</b> {html.escape(prompt)}")
        self.enhance_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.statusBar().showMessage("Enhancing request using project context…")

        thread = QThread(self)
        worker = AgentWorker(
            AgentLoop(provider, ToolRegistry()),
            AgentRequest(prompt, pack),
            work=lambda: EnhancementService.enhance(provider, prompt, pack),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._enhance_finished)
        worker.failed.connect(self._enhance_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._agent_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _enhance_failed(self, message: str) -> None:
        # Enhancing a prompt is not a coding task; do not overwrite its checkpoint.
        self.output.append(f"<b>Enhance error:</b> {html.escape(message)}")
        self.statusBar().showMessage(f"Enhance error: {message}")

    def _enhance_finished(self, result: object) -> None:
        if not isinstance(result, str) or not result.strip():
            self.output.append("<b>Enhance:</b> The provider returned an empty brief.")
            self.statusBar().showMessage("Enhance returned no usable text.")
            return
        enhanced = result.strip()
        self.prompt.setPlainText(enhanced)
        self.output.append(
            "<b>Enhanced brief (review before running):</b><br>"
            + html.escape(enhanced).replace("\n", "<br>")
        )
        self.statusBar().showMessage(
            "Request enhanced. Review or edit it, then press Run Agent."
        )

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

        self._task_original_prompt = (
            self._task_original_prompt if self._resume_requested and self._task_original_prompt
            else prompt
        )
        try:
            if self._preview is not None:
                self.stop_preview()
            pack = self._build_context(prompt)
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
            if preview is not None:
                tools.extend(
                    [
                        RunPreviewTool(preview),
                        GetPreviewLogsTool(preview),
                        StopPreviewTool(preview),
                    ]
                )
            registry = ToolRegistry(tuple(tools))
            loop = AgentLoop(provider, registry)
            request = AgentRequest(prompt, pack)
            store = self._task_store()
            if store is not None:
                store.save(TaskState(self._task_original_prompt, "running"))
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
        self.enhance_button.setEnabled(False)
        self.continue_button.setEnabled(False)
        self._resume_requested = False
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
        adapter = detect_preview_adapter(self.workspace.root)
        if adapter is None:
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
            self._save_task_state("failed" if result.failure else ("interrupted" if agent.stopped_by_limit else "completed"), agent.content)
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
        self._save_task_state("interrupted" if result.stopped_by_limit else "completed", result.content)
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
        request = AgentRequest("repair preview failure", self._build_context("repair preview failure"))
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

    def _save_task_state(self, status: str, result: str) -> None:
        store = self._task_store()
        if store is None or not self._task_original_prompt:
            return
        try:
            store.save(TaskState(self._task_original_prompt, status, result))
        except (OSError, ValueError, RuntimeError) as exc:
            self.statusBar().showMessage(f"Could not save Continue checkpoint: {exc}")
        self._refresh_continue_state()

    def _agent_failed(self, message: str) -> None:
        self._save_task_state("interrupted", message)
        self.output.append(f"<b>Agent error:</b> {html.escape(message)}")
        self.statusBar().showMessage(f"Agent error: {message}")

    def _agent_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.run_button.setEnabled(True)
        self.enhance_button.setEnabled(True)
        self._refresh_continue_state()
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
