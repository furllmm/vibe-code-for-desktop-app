from pathlib import Path

from vibe_code.runtime.adapters import (
    CppAdapter,
    DotNetAdapter,
    GoAdapter,
    JavaGradleAdapter,
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


def test_cpp_adapter_builds_conventional_entrypoint(tmp_path: Path):
    (tmp_path / "main.cpp").write_text(
        '#include <iostream>\nint main() { std::cout << "ok"; }\n',
        encoding="utf-8",
    )
    adapter = CppAdapter()
    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path) == (str(tmp_path / ".vibe-code" / "build" / "preview"),)


def test_java_gradle_adapter_requires_application_configuration(tmp_path: Path):
    (tmp_path / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "build.gradle").write_text(
        "plugins { id 'application' }\napplication { mainClass = 'demo.Main' }\n",
        encoding="utf-8",
    )
    assert JavaGradleAdapter().detect(tmp_path)
