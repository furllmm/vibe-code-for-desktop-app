import json
from pathlib import Path

from vibe_code.runtime.adapters import (
    AdapterRegistry,
    DotNetAdapter,
    ElectronAdapter,
    GoAdapter,
    NodeScriptAdapter,
    RustCargoAdapter,
)


def test_registry_prefers_specific_adapter(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "electron ."}, "devDependencies": {"electron": "^30"}}),
        encoding="utf-8",
    )
    (tmp_path / "node_modules" / "electron").mkdir(parents=True)
    (tmp_path / "node_modules" / "electron" / "cli.js").write_text("", encoding="utf-8")

    registry = AdapterRegistry((ElectronAdapter(), NodeScriptAdapter()))
    adapter = registry.detect(tmp_path)

    assert isinstance(adapter, ElectronAdapter)
    assert adapter.command(tmp_path)[0] == "node"


def test_node_script_adapter_requires_start_script(tmp_path: Path):
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"scripts": {"test": "node test.js"}}), encoding="utf-8")
    adapter = NodeScriptAdapter()

    assert not adapter.detect(tmp_path)

    package.write_text(json.dumps({"scripts": {"start": "node app.js"}}), encoding="utf-8")
    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path) == ("npm", "run", "start")


def test_rust_adapter_detects_and_resolves_target(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "hello-world"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    executable = tmp_path / "target" / "debug" / "hello-world"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    adapter = RustCargoAdapter()

    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path) == (str(executable),)


def test_go_adapter_build_command_is_shell_free_and_creates_output_dir(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.test/app\n", encoding="utf-8")
    adapter = GoAdapter()
    commands = []
    adapter._build = lambda workspace, command: commands.append(tuple(command))

    adapter.build(tmp_path)

    assert commands
    assert commands[0][0:2] == ("go", "build")
    assert (tmp_path / ".vibe-code" / "bin").is_dir()


def test_dotnet_adapter_detects_project_and_assembly(tmp_path: Path):
    project = tmp_path / "Sample.csproj"
    project.write_text(
        "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework>"
        "<AssemblyName>Sample.Desktop</AssemblyName></PropertyGroup></Project>",
        encoding="utf-8",
    )
    dll = tmp_path / "bin" / "Debug" / "net8.0" / "Sample.Desktop.dll"
    dll.parent.mkdir(parents=True)
    dll.write_text("", encoding="utf-8")
    adapter = DotNetAdapter()

    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path) == ("dotnet", str(dll))


def test_electron_requires_local_runtime(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"electron": "^30"}}), encoding="utf-8"
    )
    adapter = ElectronAdapter()

    assert not adapter.detect(tmp_path)



def test_node_adapter_rejects_non_object_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text("[]", encoding="utf-8")
    assert not NodeScriptAdapter().detect(tmp_path)


def test_node_adapter_rejects_empty_start_script(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "  "}}), encoding="utf-8"
    )
    assert not NodeScriptAdapter().detect(tmp_path)


def test_dotnet_adapter_refuses_ambiguous_projects(tmp_path: Path):
    (tmp_path / "A.csproj").write_text("<Project/>", encoding="utf-8")
    (tmp_path / "B.csproj").write_text("<Project/>", encoding="utf-8")
    assert not DotNetAdapter().detect(tmp_path)
