import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from vibe_code.app import MainWindow
from vibe_code.workspace import Workspace

_APP = QApplication.instance() or QApplication([])


def test_main_window_constructs_and_exposes_core_actions():
    window = MainWindow()
    try:
        labels = {action.text() for action in window.findChildren(QAction)}
        for expected in ("Open Workspace", "Run Preview", "Templates…", "Package Project"):
            assert expected in labels
        assert window.enhance_button.text() == "Enhance"
        assert not window.continue_button.isEnabled()
    finally:
        window.close()


def test_main_window_loads_workspace_without_errors(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    window = MainWindow()
    try:
        window.workspace = Workspace(tmp_path)
        window._set_editor_workspace(window.workspace)
        window.load_workspace(tmp_path)
        window._refresh_continue_state()
        window.refresh_context()
        assert window.project_tree.topLevelItemCount() >= 1
    finally:
        window.close()
