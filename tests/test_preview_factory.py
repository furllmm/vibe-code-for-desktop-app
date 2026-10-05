from pathlib import Path

from vibe_code.runtime.factory import detect_preview_adapter


def test_factory_prefers_rust_before_generic_fallback(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")
    adapter = detect_preview_adapter(tmp_path)
    assert type(adapter).__name__ == "RustAdapter"


def test_factory_returns_none_for_unknown_project(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    assert detect_preview_adapter(tmp_path) is None
