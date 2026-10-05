from pathlib import Path

from vibe_code.runtime.adapters import (
    DotNetAdapter,
    GoAdapter,
    NodeElectronAdapter,
    RustAdapter,
)


def test_rust_adapter_detects_cargo_project(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")
    adapter = RustAdapter()
    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path) == ("cargo", "run")


def test_go_adapter_detects_module(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example\n", encoding="utf-8")
    assert GoAdapter().detect(tmp_path)


def test_dotnet_adapter_detects_project(tmp_path: Path):
    (tmp_path / "Demo.csproj").write_text("<Project />", encoding="utf-8")
    assert DotNetAdapter().detect(tmp_path)


def test_electron_adapter_requires_start_script(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"devDependencies":{"electron":"^40.0.0"}}',
        encoding="utf-8",
    )
    assert not NodeElectronAdapter().detect(tmp_path)

    (tmp_path / "package.json").write_text(
        '{"devDependencies":{"electron":"^40.0.0"},"scripts":{"start":"electron ."}}',
        encoding="utf-8",
    )
    assert NodeElectronAdapter().detect(tmp_path)
