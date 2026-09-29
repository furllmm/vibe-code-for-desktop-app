from pathlib import Path

import pytest

from vibe_code.runtime.python_adapter import PythonPySide6Adapter


def test_detects_pyside6_import_and_finds_main(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text(
        "from PySide6.QtWidgets import QApplication\n",
        encoding="utf-8",
    )
    adapter = PythonPySide6Adapter()

    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path)[-1].endswith("main.py")


def test_detects_pyside6_requirement_and_explicit_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("PySide6>=6.7\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "desktop.py").write_text("print('ok')\n", encoding="utf-8")

    adapter = PythonPySide6Adapter("src/desktop.py")

    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path)[-1].endswith("src/desktop.py")


def test_rejects_entrypoint_escape(tmp_path: Path) -> None:
    adapter = PythonPySide6Adapter("../outside.py")

    with pytest.raises(ValueError, match="inside the workspace"):
        adapter.command(tmp_path)


def test_requires_entrypoint_when_none_can_be_inferred(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("PySide6\n", encoding="utf-8")
    adapter = PythonPySide6Adapter()

    with pytest.raises(RuntimeError, match="entrypoint"):
        adapter.command(tmp_path)
