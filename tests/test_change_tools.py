from pathlib import Path

from vibe_code.changes import ChangeManager
from vibe_code.tools.change_tools import GetChangesTool, RollbackChangesTool
from vibe_code.tools.filesystem import WorkspaceFS


def test_change_tools_list_and_rollback(tmp_path: Path) -> None:
    manager = ChangeManager(WorkspaceFS(tmp_path))
    manager.write_text("main.py", "print('x')")

    listed = GetChangesTool(manager).execute({})
    assert listed.ok
    change_id = manager.list_changes()[0].id
    assert change_id in listed.output

    result = RollbackChangesTool(manager).execute({"change_id": change_id})
    assert result.ok
    assert not (tmp_path / "main.py").exists()
