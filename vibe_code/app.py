from __future__ import annotations

import difflib
import hashlib
import html
import os
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMainWindow,
    QLabel,
    QHBoxLayout,
    QWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolBar,
    QTabWidget,
    QMessageBox,
    QInputDialog,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
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
from vibe_code.chat import ProjectChatSession
from vibe_code.chat.dialog import ProjectChatDialog
from vibe_code.editor.project_edit import ProjectEditSession
from vibe_code.editor.project_edit_dialog import ProjectEditDialog
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
from vibe_code.packaging.dialog import PackagingDialog
from vibe_code.editor import EditorPanel
from vibe_code.editor.selection_edit import propose_selection_edit
from vibe_code.editor.selection_analysis import analyze_selection
from vibe_code.editor.selection_chat import SelectionChatSession
from vibe_code.editor.selection_chat_dialog import SelectionChatDialog
from vibe_code.workspace import Workspace
from vibe_code.runtime import PreviewEngine, ProjectValidator, detect_preview_adapter


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
        self._pending_selection_edit: dict[str, object] | None = None
        self._pending_selection_analysis: dict[str, object] | None = None

        toolbar = QToolBar("Workspace")
        self.addToolBar(toolbar)
        open_action = QAction("Open Workspace", self)
        open_action.triggered.connect(self.open_workspace)
        refresh_action = QAction("Refresh Context", self)
        refresh_action.triggered.connect(self.refresh_context)
        toolbar.addAction(open_action)
        toolbar.addAction(refresh_action)
        project_chat_action = QAction("Chat with Project", self)
        project_chat_action.triggered.connect(self.open_project_chat)
        toolbar.addAction(project_chat_action)
        project_edit_action = QAction("Edit Project with AI", self)
        project_edit_action.triggered.connect(self.open_project_edit)
        toolbar.addAction(project_edit_action)
        package_action = QAction("Package Project", self)
        package_action.triggered.connect(self.open_packaging)
        toolbar.addAction(package_action)
        save_action = QAction('Save File', self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_current_file)
        toolbar.addAction(save_action)
        find_action = QAction('Find in File', self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self.show_editor_find)
        toolbar.addAction(find_action)
        goto_action = QAction("Go to Line", self)
        goto_action.setShortcut("Ctrl+G")
        goto_action.triggered.connect(self.go_to_editor_line)
        toolbar.addAction(goto_action)
        workspace_search_action = QAction("Search Workspace", self)
        workspace_search_action.setShortcut("Ctrl+Shift+F")
        workspace_search_action.triggered.connect(self.show_workspace_search)
        toolbar.addAction(workspace_search_action)
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
        self.project_tree.itemDoubleClicked.connect(self._open_tree_item)

        chat_splitter = QSplitter()
        chat_splitter.setOrientation(Qt.Orientation.Vertical)
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

        self.center_tabs = QTabWidget()
        self.center_tabs.addTab(chat_splitter, "AI Agent")
        self.editor_panel: EditorPanel | None = None
        self.editor_placeholder = QLabel("Open a workspace, then double-click a source file to edit it.")
        self.editor_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_tabs.addTab(self.editor_placeholder, "Editor")

        self.context_panel = ContextPanel()
        self.change_panel: ChangePanel | None = None

        splitter.addWidget(self.project_tree)
        splitter.addWidget(self.center_tabs)
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
            new_workspace = Workspace(Path(selected))
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Workspace error: {exc}")
            return
        if self.editor_panel is not None and not self.editor_panel.confirm_close_all():
            return
        self.workspace = new_workspace
        self._set_editor_workspace(new_workspace)
        self.load_workspace(self.workspace.root)
        self._refresh_continue_state()
        self.refresh_context()
        self.statusBar().showMessage(f"Workspace: {self.workspace.root}")

    def _set_editor_workspace(self, workspace: Workspace) -> None:
        if self.editor_panel is not None:
            index = self.center_tabs.indexOf(self.editor_panel)
            if index >= 0:
                self.center_tabs.removeTab(index)
            self.editor_panel.deleteLater()
        self.editor_panel = EditorPanel(workspace, self)
        self.editor_panel.status_message.connect(self.statusBar().showMessage)
        self.editor_panel.selection_edit_requested.connect(self._request_ai_selection_edit)
        self.editor_panel.selection_analysis_requested.connect(self._request_ai_selection_analysis)
        self.editor_panel.selection_chat_requested.connect(self._request_ai_selection_chat)
        placeholder_index = self.center_tabs.indexOf(self.editor_placeholder)
        if placeholder_index >= 0:
            self.center_tabs.removeTab(placeholder_index)
        self.center_tabs.insertTab(1, self.editor_panel, "Editor")

    def _open_tree_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if self.workspace is None:
            return
        raw_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not raw_path:
            return
        path = Path(str(raw_path))
        if path.is_dir():
            return
        if self.editor_panel is None:
            self._set_editor_workspace(self.workspace)
        try:
            self.editor_panel.open_file(path)
            self.center_tabs.setCurrentWidget(self.editor_panel)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot open file", str(exc))

    def save_current_file(self) -> None:
        if self.editor_panel is not None:
            self.editor_panel.save_current()

    def show_editor_find(self) -> None:
        if self.editor_panel is not None:
            self.center_tabs.setCurrentWidget(self.editor_panel)
            self.editor_panel.show_find()

    def show_workspace_search(self) -> None:
        if self.editor_panel is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        self.center_tabs.setCurrentWidget(self.editor_panel)
        self.editor_panel.workspace_search_input.setFocus()
        self.editor_panel.workspace_search_input.selectAll()

    def go_to_editor_line(self) -> None:
        if self.editor_panel is None or self.editor_panel.tabs.currentWidget() is None:
            self.statusBar().showMessage("Open a file in the editor first")
            return
        from vibe_code.editor.panel import CodeEditor
        editor = self.editor_panel.tabs.currentWidget()
        if not isinstance(editor, CodeEditor):
            return
        line, accepted = QInputDialog.getInt(
            self, "Go to Line", "Line number:", 1, 1, max(1, editor.blockCount())
        )
        if accepted:
            self.editor_panel.go_to_line(line)


    def open_project_chat(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        focus_paths: tuple[str, ...] = ()
        if self.editor_panel is not None:
            from vibe_code.editor.panel import CodeEditor
            editor = self.editor_panel.tabs.currentWidget()
            if isinstance(editor, CodeEditor):
                path = getattr(editor, "_workspace_path", None)
                if path is not None and self.workspace.contains(path):
                    focus_paths = (path.relative_to(self.workspace.root).as_posix(),)
        try:
            provider = self._build_provider()
            session = ProjectChatSession(
                provider,
                self.workspace,
                context_service=self.context_service,
                focus_paths=focus_paths,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Project chat unavailable", str(exc))
            return
        dialog = ProjectChatDialog(session, self.workspace.root.name, self)
        dialog.exec()

    def open_project_edit(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace first")
            return
        if self._thread is not None:
            self.statusBar().showMessage("Another AI task is already running")
            return
        instruction, accepted = QInputDialog.getMultiLineText(
            self, "Edit Project with AI",
            "Describe the project-wide change. Nothing is written until you review and apply the diff.",
            "",
        )
        if not accepted:
            return
        if not instruction.strip():
            self.statusBar().showMessage("Enter a change request first")
            return
        try:
            provider = self._build_provider()
            session = ProjectEditSession(
                provider, self.workspace, context_service=self.context_service
            )
            if (
                self._change_manager is None
                or self._change_manager.filesystem.root.resolve() != self.workspace.root.resolve()
            ):
                self._change_manager = ChangeManager(WorkspaceFS(self.workspace.root))
                if self.change_panel is not None:
                    old_index = self.right_tabs.indexOf(self.change_panel)
                    if old_index >= 0:
                        self.right_tabs.removeTab(old_index)
                    self.change_panel.deleteLater()
                    self.change_panel = None
            changes = self._change_manager
            if self.change_panel is None:
                self.change_panel = ChangePanel(changes)
                self.change_panel.rollback_requested.connect(self._rollback_change)
                self.right_tabs.addTab(self.change_panel, "Changes")
            self.change_panel.refresh()
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Project edit unavailable", str(exc))
            return
        if self._preview is not None:
            self.stop_preview()
        try:
            preview = self._build_preview_engine()
            validator = (
                ProjectValidator(self.workspace.root, preview)
                if preview is not None else None
            )
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Project validation unavailable", str(exc))
            validator = None
            preview = None

        dialog = ProjectEditDialog(
            session, changes, instruction, self, validator=validator
        )
        dialog.exec()
        if dialog.applied_change_sets:
            self.change_panel.refresh()
            if self.editor_panel is not None:
                self.editor_panel.refresh_open_files()
            self.load_workspace(self.workspace.root)
            self.refresh_context()
            self.statusBar().showMessage(
                f"{len(dialog.applied_change_sets)} approved change set(s) recorded"
            )
        if validator is not None:
            self._preview = validator.preview if validator.preview.running else None
            if self._preview is not None:
                self._preview_timer.start()

    def open_packaging(self) -> None:
        if self.workspace is None:
            self.statusBar().showMessage("Open a workspace before packaging")
            return
        dialog = PackagingDialog(self.workspace.root, self)
        dialog.exec()

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
        content_preview = "\n\n".join(
            f"{item.path}:\n{item.content[:500]}"
            + ("\n… (preview truncated)" if len(item.content) > 500 else "")
            for item in plan.files
        )
        preview = (
            f"Template: {template['name']}\n\n"
            f"New files ({len(new_files)}):\n"
            + ("\n".join(f"  + {path}" for path in new_files) or "  (none)")
            + "\n\nExisting files that will be skipped by default "
            f"({len(existing)}):\n"
            + ("\n".join(f"  • {path}" for path in existing) or "  (none)")
            + "\n\nContent preview (up to 500 characters per file):\n"
            + content_preview[:5000]
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
            preview = self._build_preview_engine()
            if preview is None:
                raise RuntimeError(
                    "No supported desktop project detected. Configure "
                    "VIBE_CODE_PREVIEW_COMMAND or add a supported project manifest."
                )
            self._preview = preview
            preview.build()
            preview.start()
            self._preview_timer.start()
            self.statusBar().showMessage(
                f"Preview is running ({type(preview.adapter).__name__})"
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
            final_logs = self._preview.read_logs()
            if final_logs:
                self.output.append(
                    "<b>Preview:</b> " + html.escape(final_logs).replace("\\n", "<br>")
                )
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



    def _request_ai_selection_chat(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict) or self.workspace is None:
            return
        try:
            if str(self.workspace.root) != snapshot.get("workspace_root"):
                raise ValueError("Workspace changed; select the code again")
            path = str(snapshot["path"])
            self.workspace.resolve(path)
            provider = self._build_provider()
            session = SelectionChatSession(
                provider,
                path,
                str(snapshot["selected"]),
                context_before=str(snapshot.get("context_before", "")),
                context_after=str(snapshot.get("context_after", "")),
            )
        except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "AI chat unavailable", str(exc))
            return

        dialog = SelectionChatDialog(session, path, self)
        dialog.exec()

    def _request_ai_selection_edit(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict) or self.workspace is None:
            return
        if self._thread is not None:
            self.statusBar().showMessage("Another AI task is already running")
            return
        instruction, accepted = QInputDialog.getMultiLineText(
            self, "AI Edit Selection", "What should the AI change in the selected code?", ""
        )
        if not accepted:
            return
        if not instruction.strip():
            self.statusBar().showMessage("Enter an edit instruction")
            return
        try:
            provider = self._build_provider()
            path = str(snapshot["path"])
            source = str(snapshot["source"])
            start = int(snapshot["start"])
            end = int(snapshot["end"])
            self.workspace.resolve(path)
            self._pending_selection_edit = snapshot
        except (KeyError, TypeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "AI edit unavailable", str(exc))
            return

        self.statusBar().showMessage("AI is preparing a selection edit…")
        self._set_selection_actions_enabled(False)
        thread = QThread(self)
        worker = AgentWorker(
            None,
            None,
            work=lambda: propose_selection_edit(
                provider, path, source, start, end, instruction
            ),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._selection_edit_finished)
        worker.failed.connect(self._agent_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._agent_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()


    def _request_ai_selection_analysis(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict) or self.workspace is None:
            return
        if self._thread is not None:
            self.statusBar().showMessage("Another AI task is already running")
            return
        try:
            provider = self._build_provider()
            if str(self.workspace.root) != snapshot.get("workspace_root"):
                raise ValueError("Workspace changed; select the code again")
            path = str(snapshot["path"])
            self.workspace.resolve(path)
            analysis_type = str(snapshot["analysis_type"])
            self._pending_selection_analysis = snapshot
        except (KeyError, TypeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "AI analysis unavailable", str(exc))
            return

        self.statusBar().showMessage("AI is analyzing the selected code…")
        self._set_selection_actions_enabled(False)
        thread = QThread(self)
        worker = AgentWorker(
            None,
            None,
            work=lambda: analyze_selection(
                provider,
                path,
                str(snapshot["selected"]),
                analysis_type,
                context_before=str(snapshot.get("context_before", "")),
                context_after=str(snapshot.get("context_after", "")),
            ),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._selection_analysis_finished)
        worker.failed.connect(self._agent_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._agent_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _selection_analysis_finished(self, result: object) -> None:
        snapshot = self._pending_selection_analysis
        self._pending_selection_analysis = None
        if not isinstance(snapshot, dict) or self.workspace is None:
            return
        if str(self.workspace.root) != snapshot.get("workspace_root"):
            self.statusBar().showMessage("Workspace changed; AI analysis discarded")
            return
        if not isinstance(result, str) or not result.strip():
            self.statusBar().showMessage("AI returned no analysis")
            return

        titles = {
            "explain": "Explain Selection",
            "bugs": "Code Review — Potential Bugs",
            "improve": "Suggested Improvements",
        }
        analysis_type = str(snapshot.get("analysis_type", "explain"))
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{titles.get(analysis_type, 'AI Analysis')} — {snapshot.get('path', '')}")
        dialog.resize(760, 560)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText(result)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout = QVBoxLayout(dialog)
        layout.addWidget(output)
        layout.addWidget(buttons)
        dialog.exec()
        self.statusBar().showMessage("AI selection analysis completed; no files were changed")

    def _set_selection_actions_enabled(self, enabled: bool) -> None:
        if self.editor_panel is None:
            return
        for name in (
            "ai_edit_selection_button",
            "ai_explain_selection_button",
            "ai_review_selection_button",
            "ai_improve_selection_button",
        ):
            button = getattr(self.editor_panel, name, None)
            if button is not None:
                button.setEnabled(enabled)

    def _selection_edit_finished(self, proposed_source: object) -> None:
        snapshot = self._pending_selection_edit
        self._pending_selection_edit = None
        if not isinstance(snapshot, dict) or self.workspace is None:
            return
        if str(self.workspace.root) != snapshot.get("workspace_root"):
            self.statusBar().showMessage("Workspace changed while AI was working; proposal discarded")
            return
        if not isinstance(proposed_source, str):
            self.statusBar().showMessage("AI returned an invalid edit")
            return
        editor = snapshot.get("editor")
        if editor is None or editor.toPlainText() != snapshot.get("source"):
            self.statusBar().showMessage("Editor content changed while AI was working; preview discarded")
            return
        try:
            path = self.workspace.resolve(str(snapshot["path"]))
            if not path.is_file():
                raise RuntimeError("The selected file was removed")
            disk_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if disk_hash != snapshot.get("disk_hash"):
                raise RuntimeError("The file changed on disk while AI was working; preview discarded")
            before = str(snapshot["source"])
            diff = "".join(difflib.unified_diff(
                before.splitlines(keepends=True),
                proposed_source.splitlines(keepends=True),
                fromfile=f"a/{snapshot['path']}",
                tofile=f"b/{snapshot['path']}",
            ))
            if not diff:
                self.statusBar().showMessage("AI proposed no changes")
                return
            preview = QPlainTextEdit()
            preview.setReadOnly(True)
            preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            preview.setPlainText(diff[:100_000] + ("\n… diff preview truncated …" if len(diff) > 100_000 else ""))
            dialog = QDialog(self)
            dialog.setWindowTitle("Review AI Selection Edit")
            dialog.resize(900, 600)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
            )
            apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
            apply_button.setText("Apply Edit")
            apply_button.clicked.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout = QVBoxLayout(dialog)
            layout.addWidget(preview)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.statusBar().showMessage("AI edit cancelled; file unchanged")
                return

            manager = self._change_manager
            if manager is None:
                manager = ChangeManager(WorkspaceFS(self.workspace.root))
                self._change_manager = manager
            manager.write_text(
                str(snapshot["path"]),
                proposed_source,
                expected_sha256=str(snapshot["disk_hash"]),
            )
            editor.setPlainText(proposed_source)
            editor._disk_hash = hashlib.sha256(proposed_source.encode("utf-8")).hexdigest()
            editor.document().setModified(False)
            if self.change_panel is None:
                self.change_panel = ChangePanel(manager)
                self.change_panel.rollback_requested.connect(self._rollback_change)
                self.right_tabs.addTab(self.change_panel, "Changes")
            self.change_panel.refresh()
            self.statusBar().showMessage(f"AI edit applied and recorded: {snapshot['path']}")
        except (OSError, ValueError, KeyError, PermissionError, RuntimeError) as exc:
            QMessageBox.warning(self, "AI edit not applied", str(exc))
            self.statusBar().showMessage(f"AI edit not applied: {exc}")

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
        self._set_selection_actions_enabled(True)
        if self._pending_selection_analysis is not None:
            self._pending_selection_analysis = None
        if self._pending_selection_edit is not None:
            self._pending_selection_edit = None
        self.enhance_button.setEnabled(True)
        self._refresh_continue_state()
        failure = self._pending_recovery_failure
        self._pending_recovery_failure = None
        if failure is not None:
            QTimer.singleShot(0, lambda: self._handle_preview_failure(failure))

    def closeEvent(self, event) -> None:
        if self.editor_panel is not None and not self.editor_panel.confirm_close_all():
            event.ignore()
            return
        self.stop_preview()
        super().closeEvent(event)

    def load_workspace(self, root: Path) -> None:
        self.project_tree.clear()
        self._add_tree(root, self.project_tree.invisibleRootItem())

    def _add_tree(self, path: Path, parent: QTreeWidgetItem) -> None:
        if path != path.anchor and path.name.startswith("."):
            return
        item = QTreeWidgetItem(parent, [path.name or str(path)])
        item.setData(0, Qt.ItemDataRole.UserRole, str(path))
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
