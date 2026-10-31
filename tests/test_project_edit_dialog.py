import hashlib
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from vibe_code.changes import ChangeManager
from vibe_code.context.models import ContextItem, ContextPack
from vibe_code.editor.project_edit import ProjectEditSession
from vibe_code.editor.project_edit_dialog import ProjectEditDialog
from vibe_code.providers.base import ProviderResponse
from vibe_code.runtime.validation import ValidationResult, ValidationStep
from vibe_code.tools.filesystem import WorkspaceFS
from vibe_code.workspace import Workspace


_APP = QApplication.instance() or QApplication([])


class FakeContext:
    def __init__(self, root):
        self.root = root

    def build(self, request):
        path = self.root / "main.py"
        return ContextPack((
            ContextItem(path, "file", 10, "match", path.read_text(), 1, 1),
        ), 10)


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, request):
        return ProviderResponse(self.responses.pop(0))


class FakeValidator:
    def __init__(self, results):
        self.results = list(results)

    def run(self):
        return self.results.pop(0)


def make_response(before, after):
    return json.dumps({"files": [{
        "path": "main.py",
        "original_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "content": after,
    }]})


def wait_for_idle(dialog, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while dialog._thread is not None and time.monotonic() < deadline:
        _APP.processEvents()
        time.sleep(0.005)
    _APP.processEvents()
    assert dialog._thread is None


def make_dialog(tmp_path, validator):
    original = "print('before')\n"
    first = "print('first')\n"
    second = "print('repaired')\n"
    (tmp_path / "main.py").write_bytes(original.encode())
    provider = FakeProvider([
        make_response(original, first),
        make_response(first, second),
    ])
    session = ProjectEditSession(provider, Workspace(tmp_path), FakeContext(tmp_path))
    manager = ChangeManager(WorkspaceFS(tmp_path))
    dialog = ProjectEditDialog(session, manager, "Update the greeting", validator=validator)
    wait_for_idle(dialog)
    return dialog, tmp_path / "main.py"


def test_validation_requires_explicit_trust_and_confirmation(tmp_path, monkeypatch):
    result = ValidationResult(True, (ValidationStep("Build", True, "ok"),), False)
    validator = FakeValidator([result])
    dialog, target = make_dialog(tmp_path, validator)
    try:
        assert dialog.validate_button.isEnabled()
        assert not dialog.trust.isChecked()
        warnings = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *args, **kwargs: warnings.append(args[1]),
        )
        dialog.apply_and_validate()
        assert warnings
        assert target.read_text() == "print('before')\n"
        assert validator.results
    finally:
        dialog.close()


def test_failed_validation_requires_reviewed_ai_repair_then_revalidates(tmp_path, monkeypatch):
    failure = ValidationResult(
        False, (ValidationStep("Tests", False, "AssertionError: expected 2"),), False
    )
    success = ValidationResult(
        True, (ValidationStep("Tests", True, "2 passed"),), True
    )
    validator = FakeValidator([failure, success])
    dialog, target = make_dialog(tmp_path, validator)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        dialog.trust.setChecked(True)
        dialog.apply_and_validate()
        wait_for_idle(dialog)
        assert target.read_text() == "print('first')\n"
        assert dialog.validation_result is failure
        assert dialog.repair_button.isEnabled()
        assert "AssertionError" in dialog.preview.toPlainText()

        dialog.ask_ai_for_fix()
        wait_for_idle(dialog)
        assert "print('repaired')" in dialog.preview.toPlainText()
        assert dialog.validate_button.isEnabled()

        dialog.apply_and_validate()
        wait_for_idle(dialog)
        assert dialog.result() == ProjectEditDialog.DialogCode.Accepted
        assert target.read_text() == "print('repaired')\n"
        assert len(dialog.applied_change_sets) == 2
    finally:
        if dialog.isVisible():
            dialog.close()


def test_cancel_after_approved_apply_does_not_undo_user_changes(tmp_path, monkeypatch):
    validator = FakeValidator([])
    dialog, target = make_dialog(tmp_path, validator)
    try:
        dialog.apply_changes()
        assert target.read_text() == "print('first')\n"
        assert len(dialog.applied_change_sets) == 1
        assert dialog.result() == ProjectEditDialog.DialogCode.Accepted
    finally:
        dialog.close()
