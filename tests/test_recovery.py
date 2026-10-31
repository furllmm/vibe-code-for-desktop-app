from pathlib import Path

import pytest

from vibe_code.changes import ChangeManager
from vibe_code.tools.filesystem import WorkspaceFS


def test_rollback_many_preflights_before_mutating(tmp_path: Path):
    path = tmp_path / "app.py"
    path.write_text("old\n", encoding="utf-8")
    manager = ChangeManager(WorkspaceFS(tmp_path))

    manager.write_text("app.py", "new\n")
    second = manager.write_text("new.py", "generated\n")
    changes = manager.list_changes()
    ids = tuple(change.id for change in changes[:2])

    path.write_text("externally changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after"):
        manager.rollback_many(ids)

    assert path.read_text(encoding="utf-8") == "externally changed\n"
    assert (tmp_path / second.path).exists()
