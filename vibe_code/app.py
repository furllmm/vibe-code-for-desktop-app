from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vibe Code for Desktop Apps")
        self.resize(1200, 760)
        splitter = QSplitter()
        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderLabel("Project")
        self.chat = QTextEdit()
        self.chat.setPlaceholderText("Describe the desktop app or change you want to make…")
        splitter.addWidget(self.project_tree)
        splitter.addWidget(self.chat)
        splitter.setSizes([280, 920])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready — context-engineering foundation initialized")

    def load_workspace(self, root: Path) -> None:
        self.project_tree.clear()
        self._add_tree(root, self.project_tree.invisibleRootItem())

    def _add_tree(self, path: Path, parent: QTreeWidgetItem) -> None:
        if path.name.startswith(".") and path != path.anchor:
            return
        item = QTreeWidgetItem(parent, [path.name])
        if path.is_dir():
            try:
                children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                return
            for child in children[:500]:
                self._add_tree(child, item)

def run() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
