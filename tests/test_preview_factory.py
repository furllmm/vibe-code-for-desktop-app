import shutil
from pathlib import Path

import pytest

from vibe_code.runtime import CppAdapter, RustCargoAdapter, CMakeAdapter
from vibe_code.runtime.factory import detect_preview_adapter


def test_factory_prefers_rust_before_generic_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIBE_CODE_PREVIEW_COMMAND", raising=False)
    (tmp_path / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")
    assert isinstance(detect_preview_adapter(tmp_path), RustCargoAdapter)


def test_factory_returns_none_for_unknown_project(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIBE_CODE_PREVIEW_COMMAND", raising=False)
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    assert detect_preview_adapter(tmp_path) is None


def test_factory_honours_explicit_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VIBE_CODE_PREVIEW_COMMAND", "python -V")
    adapter = detect_preview_adapter(tmp_path)
    assert adapter.command(tmp_path) == ("python", "-V")


def test_conventional_cpp_is_fallback_after_cmake(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIBE_CODE_PREVIEW_COMMAND", raising=False)
    (tmp_path / "main.cpp").write_text("int main(){return 0;}\n", encoding="utf-8")
    assert isinstance(detect_preview_adapter(tmp_path), CppAdapter)
    (tmp_path / "CMakeLists.txt").write_text("project(x)\n", encoding="utf-8")
    assert isinstance(detect_preview_adapter(tmp_path), CMakeAdapter)


@pytest.mark.skipif(shutil.which("c++") is None, reason="C++ compiler not installed")
def test_conventional_cpp_builds_and_runs(tmp_path: Path):
    (tmp_path / "main.cpp").write_text("int main(){return 0;}\n", encoding="utf-8")
    adapter = CppAdapter()
    adapter.build(tmp_path)
    command = adapter.command(tmp_path)
    assert Path(command[0]).is_file()
