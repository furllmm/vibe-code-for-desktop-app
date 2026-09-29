from pathlib import Path

import pytest

from vibe_code.changes import ChangeManager
from vibe_code.tools.filesystem import WorkspaceFS
from vibe_code.tools.workspace_tools import WriteFileTool


def test_write_is_atomic_and_rollback_restores_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("before\n", encoding="utf-8")
    manager = ChangeManager(WorkspaceFS(tmp_path))

    record = manager.write_text("app.py", "after\n")

    assert target.read_text(encoding="utf-8") == "after\n"
    assert record.before_sha256
    assert record.after_sha256 != record.before_sha256
    assert record.backup_path
    manager.rollback(manager.list_changes()[0].id)
    assert target.read_text(encoding="utf-8") == "before\n"


def test_rollback_removes_new_file(tmp_path: Path) -> None:
    manager = ChangeManager(WorkspaceFS(tmp_path))
    manager.write_text("new.txt", "created")
    change_id = manager.list_changes()[0].id

    manager.rollback(change_id)

    assert not (tmp_path / "new.txt").exists()


def test_rollback_refuses_external_changes(tmp_path: Path) -> None:
    manager = ChangeManager(WorkspaceFS(tmp_path))
    manager.write_text("app.py", "agent")
    change_id = manager.list_changes()[0].id
    (tmp_path / "app.py").write_text("human edit", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after"):
        manager.rollback(change_id)


def test_internal_state_cannot_be_written_by_agent(tmp_path: Path) -> None:
    manager = ChangeManager(WorkspaceFS(tmp_path))

    with pytest.raises(PermissionError):
        manager.write_text(".vibe-code/changes/manifest.json", "tamper")


def test_write_file_uses_change_manager(tmp_path: Path) -> None:
    filesystem = WorkspaceFS(tmp_path)
    manager = ChangeManager(filesystem)
    result = WriteFileTool(filesystem, manager).execute(
        {"path": "main.py", "content": "print('ok')"}
    )

    assert result.ok
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('ok')"
    assert len(manager.list_changes()) == 1
