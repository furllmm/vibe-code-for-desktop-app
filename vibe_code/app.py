from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QSplitter,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from vibe_code.context.models import ContextRequest
from vibe_code.context.panel import ContextPanel
from vibe_code.context.service import ContextService
from vibe_code.workspace import Workspace


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vibe Code for Desktop Apps")
        self.resize(1280, 800)
        self.workspace: Workspace | None = None
        self.context_service = ContextService()

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
        self.chat = QTextEdit()
        self.chat.setPlaceholderText(
            "Describe the desktop app or change you want to make…"
        )
        self.context_panel = ContextPanel()

        splitter.addWidget(self.project_tree)
        splitter.addWidget(self.chat)
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

        prompt = self.chat.toPlainText().strip() or "project structure and metadata"
        pack = self.context_service.build(
            ContextRequest(prompt, self.workspace.root, token_budget=12000)
        )
        self.context_panel.show_pack(pack)
        self.statusBar().showMessage(
            f"Context: {len(pack.items)} files • ~{pack.estimated_tokens} tokens"
        )

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
