from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Protocol

from .models import PackageRequest, PackagingPlan


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")


def _safe_name(value: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value.strip()):
        raise ValueError("Package name must be 1-80 safe characters")
    return value.strip()


def _workspace_path(workspace: Path, value: str) -> Path:
    candidate = (workspace / value).resolve()
    root = workspace.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Packaging paths must stay inside the workspace")
    return candidate


class PackagingAdapter(Protocol):
    backend: str

    def create_plan(self, workspace: Path, request: PackageRequest) -> PackagingPlan:
        ...


class PyInstallerAdapter:
    backend = "pyinstaller"

    def create_plan(self, workspace: Path, request: PackageRequest) -> PackagingPlan:
        if importlib.util.find_spec("PyInstaller") is None:
            raise RuntimeError(
                "PyInstaller is not installed in the IDE's Python environment. "
                "Install it explicitly before packaging."
            )
        if not request.entrypoint:
            raise ValueError("Python packaging requires an explicit entrypoint")
        entrypoint = _workspace_path(workspace, request.entrypoint)
        if not entrypoint.is_file():
            raise FileNotFoundError(f"Entrypoint not found: {request.entrypoint}")
        output = _workspace_path(workspace, request.output_dir)
        work = _workspace_path(workspace, ".vibe-code/packaging/pyinstaller-work")
        spec = _workspace_path(workspace, ".vibe-code/packaging/spec")
        command = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--name", _safe_name(request.name), "--distpath", str(output),
            "--workpath", str(work), "--specpath", str(spec),
            "--onefile" if request.one_file else "--onedir", str(entrypoint),
        ]
        return PackagingPlan(
            self.backend, tuple(command), output,
            "Build a Python desktop bundle with PyInstaller",
        )


class CPackAdapter:
    backend = "cpack"
    formats = {
        "zip": "ZIP", "tgz": "TGZ", "deb": "DEB", "rpm": "RPM",
        "nsis": "NSIS", "ifw": "IFW", "dragndrop": "DragNDrop",
        "productbuild": "productbuild",
    }

    def create_plan(self, workspace: Path, request: PackageRequest) -> PackagingPlan:
        if not (workspace / "CMakeLists.txt").is_file():
            raise ValueError("CPack requires a CMake project")
        executable = shutil.which("cpack")
        if not executable:
            raise RuntimeError("cpack was not found; install CMake's CPack component")
        package_type = request.package_type.lower()
        if package_type not in self.formats:
            raise ValueError(f"Unsupported CPack format: {request.package_type}")
        generator = self.formats[package_type]
        config = _workspace_path(
            workspace, ".vibe-code/build/cmake/CPackConfig.cmake"
        )
        if not config.is_file():
            raise RuntimeError("CPackConfig.cmake is missing; configure the CMake project first")
        output = _workspace_path(workspace, request.output_dir)
        return PackagingPlan(
            self.backend,
            (executable, "--config", str(config), "-G", generator,
             "-B", str(output)),
            output,
            f"Create a {package_type.upper()} package with the project's CPack configuration",
        )


class JavaJPackageAdapter:
    backend = "jpackage"

    def create_plan(self, workspace: Path, request: PackageRequest) -> PackagingPlan:
        if request.package_type != "app-image":
            raise ValueError(
                "The first Java packaging version supports app-image only; "
                "native installers require platform-specific toolchains."
            )
        executable = shutil.which("jpackage")
        if not executable:
            raise RuntimeError("jpackage was not found; install a full JDK")
        if not request.entrypoint:
            raise ValueError("Java packaging requires an executable JAR path")
        jar = _workspace_path(workspace, request.entrypoint)
        if not jar.is_file() or jar.suffix.lower() != ".jar":
            raise FileNotFoundError("A valid executable JAR is required")
        try:
            with zipfile.ZipFile(jar) as archive:
                manifest_name = next(
                    (name for name in archive.namelist()
                     if name.upper() == "META-INF/MANIFEST.MF"), None
                )
                manifest = archive.read(manifest_name).decode("utf-8", errors="replace") if manifest_name else ""
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(f"Invalid JAR file: {exc}") from exc
        if not any(line.strip().lower().startswith("main-class:") for line in manifest.splitlines()):
            raise ValueError("JAR manifest must declare Main-Class")
        output = _workspace_path(workspace, request.output_dir)
        return PackagingPlan(
            self.backend,
            (executable, "--type", "app-image", "--name", _safe_name(request.name),
             "--input", str(jar.parent), "--main-jar", jar.name, "--dest", str(output)),
            output,
            "Create a Java application image with jpackage",
        )


class AppImageAdapter:
    """Wrap an already prepared AppDir with appimagetool on Linux."""

    backend = "appimage"

    def create_plan(self, workspace: Path, request: PackageRequest) -> PackagingPlan:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("AppImage packaging is available only on Linux")
        executable = shutil.which("appimagetool")
        if not executable:
            raise RuntimeError("appimagetool was not found; install it before packaging")
        if not request.entrypoint:
            raise ValueError("AppImage packaging requires an AppDir path")
        appdir = _workspace_path(workspace, request.entrypoint)
        if not appdir.is_dir():
            raise NotADirectoryError(f"AppDir not found: {request.entrypoint}")
        if not any(appdir.glob("*.desktop")):
            raise ValueError("AppDir must contain a .desktop file at its root")
        if not any(appdir.glob("*.png")):
            raise ValueError("AppDir must contain a PNG application icon at its root")
        output = _workspace_path(workspace, request.output_dir)
        artifact = output / f"{_safe_name(request.name)}.AppImage"
        return PackagingPlan(
            self.backend, (executable, str(appdir), str(artifact)), output,
            "Create an AppImage from the supplied AppDir",
        )


class PackagingRegistry:
    def __init__(self, adapters: tuple[PackagingAdapter, ...] | None = None) -> None:
        selected = adapters or (
            PyInstallerAdapter(), CPackAdapter(), JavaJPackageAdapter(), AppImageAdapter()
        )
        self._adapters = {adapter.backend: adapter for adapter in selected}

    def create_plan(self, workspace: Path, request: PackageRequest) -> PackagingPlan:
        try:
            adapter = self._adapters[request.backend]
        except KeyError as exc:
            raise ValueError(f"Unsupported packaging backend: {request.backend}") from exc
        root = workspace.resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        return adapter.create_plan(root, request)
