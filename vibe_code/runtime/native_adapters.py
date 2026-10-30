from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Sequence


class CMakeAdapter:
    """C/C++ preview adapter using CMake's file API to locate one executable."""

    build_dir = Path(".vibe-code") / "build" / "cmake"
    query_dir = build_dir / ".cmake" / "api" / "v1" / "query"

    def detect(self, workspace: Path) -> bool:
        return (workspace / "CMakeLists.txt").is_file()

    def build(self, workspace: Path) -> None:
        query = workspace / self.query_dir
        query.mkdir(parents=True, exist_ok=True)
        (query / "codemodel-v2").touch(exist_ok=True)
        build = workspace / self.build_dir
        self._run(workspace, ("cmake", "-S", str(workspace), "-B", str(build),
                              "-DCMAKE_BUILD_TYPE=Debug"))
        self._run(workspace, ("cmake", "--build", str(build), "--config", "Debug"))

    @staticmethod
    def _run(workspace: Path, command: Sequence[str]) -> None:
        try:
            result = subprocess.run(
                list(command), cwd=workspace, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", timeout=600, check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Build tool not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            raise RuntimeError(f"CMake timed out after 600s.\\n{str(output)[-8000:]}") from exc
        if result.returncode:
            raise RuntimeError(
                f"CMake command failed (exit {result.returncode}).\\n{result.stdout[-8000:]}"
            )

    def command(self, workspace: Path) -> Sequence[str]:
        reply = workspace / self.build_dir / ".cmake" / "api" / "v1" / "reply"
        indexes = sorted(reply.glob("index-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not indexes:
            raise RuntimeError("CMake file API reply is missing; build the project first")
        try:
            index = json.loads(indexes[0].read_text(encoding="utf-8"))
            codemodel_ref = index["reply"]["codemodel-v2"]
            codemodel = json.loads((reply / codemodel_ref["jsonFile"]).read_text(encoding="utf-8"))
            configurations = codemodel.get("configurations", [])
            if not configurations:
                raise ValueError("no CMake build configuration")
            targets = configurations[0].get("targets", [])
            executables = []
            for target in targets:
                if target.get("type") != "EXECUTABLE":
                    continue
                target_json = json.loads(
                    (reply / target["jsonFile"]).read_text(encoding="utf-8")
                )
                for artifact in target_json.get("artifacts", []):
                    path = workspace / self.build_dir / artifact["path"]
                    if path.is_file():
                        executables.append(path)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not resolve CMake executable target: {exc}") from exc
        unique = list(dict.fromkeys(executables))
        if not unique:
            raise RuntimeError("CMake build has no executable target to preview")
        if len(unique) > 1:
            names = ", ".join(path.name for path in unique[:8])
            raise RuntimeError(
                f"Multiple CMake executables found ({names}). Configure a single preview target."
            )
        return (str(unique[0]),)


class JavaAdapter:
    """Builds Maven/Gradle projects and runs a single executable JAR."""

    def __init__(self) -> None:
        self.build_system: str | None = None

    def detect(self, workspace: Path) -> bool:
        has_maven = (workspace / "pom.xml").is_file()
        has_gradle = any((workspace / name).is_file() for name in
                         ("build.gradle", "build.gradle.kts"))
        if has_maven == has_gradle:
            return False
        self.build_system = "maven" if has_maven else "gradle"
        return True

    def build(self, workspace: Path) -> None:
        if self.build_system is None:
            self.detect(workspace)
        if self.build_system == "maven":
            command = ("mvn", "-B", "-DskipTests", "package")
        elif self.build_system == "gradle":
            command = ("gradle", "--no-daemon", "build", "-x", "test")
        else:
            raise RuntimeError("No unambiguous Maven or Gradle project found")
        try:
            result = subprocess.run(
                list(command), cwd=workspace, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", timeout=900, check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Build tool not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            raise RuntimeError(f"Java build timed out after 900s.\\n{str(output)[-8000:]}") from exc
        if result.returncode:
            raise RuntimeError(
                f"Java build failed (exit {result.returncode}).\\n{result.stdout[-8000:]}"
            )

    @staticmethod
    def _has_main_class(jar: Path) -> bool:
        import zipfile

        try:
            with zipfile.ZipFile(jar) as archive:
                manifest = next(
                    (name for name in archive.namelist()
                     if name.upper() == "META-INF/MANIFEST.MF"),
                    None,
                )
                if manifest is None:
                    return False
                text = archive.read(manifest).decode("utf-8", errors="replace")
                return any(
                    line.strip().lower().startswith("main-class:")
                    for line in text.splitlines()
                )
        except (OSError, zipfile.BadZipFile):
            return False

    def command(self, workspace: Path) -> Sequence[str]:
        output = workspace / ("target" if self.build_system == "maven" else "build" / Path("libs"))
        jars = sorted(
            path for path in output.glob("*.jar")
            if not any(token in path.name.lower()
                       for token in ("-sources", "-javadoc", "-tests", "original-"))
            and self._has_main_class(path)
        ) if output.is_dir() else []
        if len(jars) != 1:
            raise RuntimeError(
                "Expected exactly one executable JAR with a Main-Class manifest; "
                "configure a runnable/fat JAR before previewing."
            )
        return ("java", "-jar", str(jars[0]))
