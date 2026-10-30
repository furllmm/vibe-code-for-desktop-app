import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from vibe_code.editor.panel import EditorPanel
from vibe_code.workspace import Workspace


_APP = QApplication.instance() or QApplication([])


def test_editor_opens_saves_and_reopens_workspace_file(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("print('hello')\n", encoding="utf-8")
    panel = EditorPanel(Workspace(tmp_path))
    editor = panel.open_file(source)
    editor.appendPlainText("print('saved')")
    assert editor.document().isModified()
    assert panel.save_current()
    assert "print('saved')" in source.read_text(encoding="utf-8")
    assert not editor.document().isModified()


def test_editor_reuses_existing_tab_and_supports_multiple_files(tmp_path):
    first_path = tmp_path / "app.py"
    second_path = tmp_path / "config.json"
    first_path.write_text("def main():\n    return True\n", encoding="utf-8")
    second_path.write_text('{"enabled": true}\n', encoding="utf-8")
    panel = EditorPanel(Workspace(tmp_path))
    first = panel.open_file(first_path)
    assert panel.open_file(first_path) is first
    panel.open_file(second_path)
    assert panel.tabs.count() == 2
    assert panel.tabs.tabText(0) == "app.py"
    assert panel.tabs.tabText(1) == "config.json"


def test_editor_rejects_path_escape_binary_and_oversized_files(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    binary = root / "data.bin"
    binary.write_bytes(b"\x00\x01\x02")
    large = root / "large.txt"
    large.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    panel = EditorPanel(Workspace(root))

    import pytest
    with pytest.raises(ValueError, match="escapes workspace"):
        panel.open_file(outside)
    with pytest.raises(ValueError, match="Binary"):
        panel.open_file(binary)
    with pytest.raises(ValueError, match="2 MiB"):
        panel.open_file(large)


def test_editor_refuses_to_overwrite_external_modification(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_text("original\n", encoding="utf-8")
    panel = EditorPanel(Workspace(tmp_path))
    editor = panel.open_file(source)
    editor.appendPlainText("# local edit")
    source.write_text("external edit\n", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

    assert not panel.save_current()
    assert source.read_text(encoding="utf-8") == "external edit\n"
    assert editor.document().isModified()


def test_editor_does_not_recreate_file_deleted_externally(tmp_path, monkeypatch):
    source = tmp_path / "removed.py"
    source.write_text("original\n", encoding="utf-8")
    panel = EditorPanel(Workspace(tmp_path))
    editor = panel.open_file(source)
    editor.appendPlainText("# pending change")
    source.unlink()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

    assert not panel.save_current()
    assert not source.exists()
    assert editor.document().isModified()
