import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibe_code.chat.dialog import ProjectChatDialog
from vibe_code.chat.project_chat import ProjectChatSession
from vibe_code.workspace import Workspace


_APP = QApplication.instance() or QApplication([])


class UnusedProvider:
    def complete(self, request):
        raise AssertionError("Provider must not be called for an empty question")


def test_project_chat_dialog_is_read_only_and_rejects_empty_question(tmp_path):
    session = ProjectChatSession(UnusedProvider(), Workspace(tmp_path))
    dialog = ProjectChatDialog(session, "sample-project")
    assert "Read-only" in dialog.status.text()
    assert "configured AI provider" in dialog.status.text()

    dialog.send_question()

    assert dialog.status.text() == "Enter a question first."
    assert dialog._thread is None
    dialog.reject()
