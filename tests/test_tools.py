from pathlib import Path

import pytest

from vibe_code.tools.filesystem import WorkspaceFS
from vibe_code.tools.registry import ToolRegistry
from vibe_code.tools.workspace_tools import ReadFileTool, WriteFileTool


def test_registry_exposes_only_registered_tools() -> None:
    fs = WorkspaceFS(Path("."))
    registry = ToolRegistry((ReadFileTool(fs),))
    assert registry.names() == ("read_file",)
    with pytest.raises(KeyError):
        registry.get("write_file")


def test_read_tool_is_workspace_scoped(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    tool = ReadFileTool(WorkspaceFS(tmp_path))

    result = tool.execute({"path": "ok.txt"})
    assert result.ok
    assert result.output == "hello"

    escaped = tool.execute({"path": "../outside.txt"})
    assert not escaped.ok


def test_write_tool_writes_utf8_inside_workspace(tmp_path: Path) -> None:
    tool = WriteFileTool(WorkspaceFS(tmp_path))

    result = tool.execute({"path": "src/main.py", "content": "print('ok')\n"})
    assert result.ok
    assert (tmp_path / "src/main.py").read_text(encoding="utf-8") == "print('ok')\n"


def test_write_tool_validates_arguments(tmp_path: Path) -> None:
    tool = WriteFileTool(WorkspaceFS(tmp_path))
    assert not tool.execute({"path": ""}).ok
    assert not tool.execute({"path": "a.txt", "content": 123}).ok
