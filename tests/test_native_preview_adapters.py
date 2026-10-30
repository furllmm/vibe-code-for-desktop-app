import json
from pathlib import Path
import zipfile

import pytest

from vibe_code.runtime.native_adapters import CMakeAdapter, JavaAdapter


def test_cmake_detects_manifest_and_resolves_one_executable(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(sample)", encoding="utf-8")
    adapter = CMakeAdapter()
    assert adapter.detect(tmp_path)

    reply = tmp_path / adapter.build_dir / ".cmake" / "api" / "v1" / "reply"
    reply.mkdir(parents=True)
    executable = tmp_path / adapter.build_dir / "sample"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("", encoding="utf-8")
    (reply / "target-sample.json").write_text(
        json.dumps({"type": "EXECUTABLE", "artifacts": [{"path": "sample"}]}),
        encoding="utf-8",
    )
    (reply / "codemodel.json").write_text(
        json.dumps({"configurations": [{"targets": [
            {"type": "EXECUTABLE", "jsonFile": "target-sample.json"}
        ]}]}), encoding="utf-8"
    )
    (reply / "index-test.json").write_text(
        json.dumps({"reply": {"codemodel-v2": {"jsonFile": "codemodel.json"}}}),
        encoding="utf-8",
    )

    assert adapter.command(tmp_path) == (str(executable),)


def test_cmake_refuses_ambiguous_executable_targets(tmp_path: Path):
    adapter = CMakeAdapter()
    reply = tmp_path / adapter.build_dir / ".cmake" / "api" / "v1" / "reply"
    reply.mkdir(parents=True)
    for name in ("one", "two"):
        artifact = tmp_path / adapter.build_dir / name
        artifact.write_text("", encoding="utf-8")
        (reply / f"target-{name}.json").write_text(
            json.dumps({"type": "EXECUTABLE", "artifacts": [{"path": name}]}),
            encoding="utf-8",
        )
    (reply / "codemodel.json").write_text(
        json.dumps({"configurations": [{"targets": [
            {"type": "EXECUTABLE", "jsonFile": "target-one.json"},
            {"type": "EXECUTABLE", "jsonFile": "target-two.json"},
        ]}]}), encoding="utf-8"
    )
    (reply / "index-test.json").write_text(
        json.dumps({"reply": {"codemodel-v2": {"jsonFile": "codemodel.json"}}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Multiple CMake executables"):
        adapter.command(tmp_path)


def _make_runnable_jar(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as jar:
        jar.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMain-Class: demo.Main\n")


def test_java_maven_detects_and_launches_unique_runnable_jar(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    jar = tmp_path / "target" / "demo.jar"
    _make_runnable_jar(jar)
    adapter = JavaAdapter()

    assert adapter.detect(tmp_path)
    assert adapter.command(tmp_path) == ("java", "-jar", str(jar))


def test_java_gradle_detects_gradle_kts(tmp_path: Path):
    (tmp_path / "build.gradle.kts").write_text("plugins {}", encoding="utf-8")
    adapter = JavaAdapter()

    assert adapter.detect(tmp_path)
    assert adapter.build_system == "gradle"


def test_java_refuses_non_executable_or_ambiguous_jars(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    adapter = JavaAdapter()
    adapter.detect(tmp_path)
    plain = tmp_path / "target" / "library.jar"
    plain.parent.mkdir(parents=True)
    with zipfile.ZipFile(plain, "w") as jar:
        jar.writestr("library.txt", "not executable")

    with pytest.raises(RuntimeError, match="exactly one executable JAR"):
        adapter.command(tmp_path)


def test_java_refuses_ambiguous_build_manifests(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("plugins {}", encoding="utf-8")
    assert not JavaAdapter().detect(tmp_path)
