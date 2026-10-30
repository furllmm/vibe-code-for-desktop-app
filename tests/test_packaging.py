from pathlib import Path
import sys
import zipfile

import pytest

from vibe_code.packaging import (
    AppImageAdapter,
    JavaJPackageAdapter,
    PackageRequest,
    PackagingEngine,
    PackagingPlan,
    PackagingRegistry,
    PyInstallerAdapter,
)


def test_python_packaging_requires_explicit_entrypoint_and_pyinstaller(tmp_path, monkeypatch):
    entry = tmp_path / "main.py"
    entry.write_text("print('hello')", encoding="utf-8")
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())

    plan = PyInstallerAdapter().create_plan(
        tmp_path,
        PackageRequest("pyinstaller", "Demo App", entrypoint="main.py", one_file=True),
    )

    assert plan.command[0:3] == (sys.executable, "-m", "PyInstaller")
    assert "--onefile" in plan.command
    assert str(entry) == plan.command[-1]


def test_python_packaging_rejects_path_escape(tmp_path, monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    outside = tmp_path.parent / "outside.py"
    outside.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the workspace"):
        PyInstallerAdapter().create_plan(
            tmp_path,
            PackageRequest("pyinstaller", "Demo", entrypoint="../outside.py"),
        )


def test_python_packaging_rejects_unsafe_name(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())

    with pytest.raises(ValueError, match="Package name"):
        PyInstallerAdapter().create_plan(
            tmp_path,
            PackageRequest("pyinstaller", "../bad", entrypoint="main.py"),
        )


def test_java_jpackage_requires_executable_jar_and_creates_plan(tmp_path, monkeypatch):
    jar = tmp_path / "app.jar"
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr(
            "META-INF/MANIFEST.MF",
            "Manifest-Version: 1.0\nMain-Class: sample.Main\n",
        )
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/jpackage")

    plan = JavaJPackageAdapter().create_plan(
        tmp_path,
        PackageRequest("jpackage", "Sample", entrypoint="app.jar"),
    )

    assert plan.command[0] == "/usr/bin/jpackage"
    assert "--main-jar" in plan.command
    assert plan.command[-2] == "--dest"


def test_java_jpackage_rejects_jar_without_main_class(tmp_path, monkeypatch):
    jar = tmp_path / "library.jar"
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("library.txt", "data")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/jpackage")

    with pytest.raises(ValueError, match="Main-Class"):
        JavaJPackageAdapter().create_plan(
            tmp_path,
            PackageRequest("jpackage", "Library", entrypoint="library.jar"),
        )


def test_packaging_engine_requires_issued_plan_and_explicit_trust(tmp_path):
    class FakeAdapter:
        backend = "fake"

        def create_plan(self, workspace, request):
            return PackagingPlan("fake", (sys.executable, "-c", "pass"), workspace / "dist", "fake")

    engine = PackagingEngine(tmp_path, PackagingRegistry((FakeAdapter(),)))
    plan = engine.create_plan(PackageRequest("fake", "Demo"))

    with pytest.raises(PermissionError, match="Explicitly trust"):
        engine.execute(plan)

    forged = PackagingPlan("fake", (sys.executable, "-c", "print('bad')"), tmp_path / "dist", "forged")
    with pytest.raises(ValueError, match="not created by this engine"):
        engine.execute(forged, trusted_workspace=True)


def test_packaging_registry_rejects_unknown_backend(tmp_path):
    with pytest.raises(ValueError, match="Unsupported packaging backend"):
        PackagingEngine(tmp_path).create_plan(PackageRequest("unknown", "Demo"))



def test_cpack_plan_uses_generated_config_and_canonical_generator(tmp_path, monkeypatch):
    config = tmp_path / ".vibe-code" / "build" / "cmake" / "CPackConfig.cmake"
    config.parent.mkdir(parents=True)
    config.write_text("set(CPACK_PACKAGE_NAME Demo)", encoding="utf-8")
    (tmp_path / "CMakeLists.txt").write_text("project(Demo)", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/cpack")

    from vibe_code.packaging import CPackAdapter

    plan = CPackAdapter().create_plan(
        tmp_path,
        PackageRequest("cpack", "Demo", package_type="dragndrop"),
    )

    assert plan.command[0] == "/usr/bin/cpack"
    assert plan.command[plan.command.index("-G") + 1] == "DragNDrop"
    assert not plan.output_dir.exists()


def test_cpack_rejects_unsupported_generator(tmp_path, monkeypatch):
    config = tmp_path / ".vibe-code" / "build" / "cmake" / "CPackConfig.cmake"
    config.parent.mkdir(parents=True)
    config.write_text("", encoding="utf-8")
    (tmp_path / "CMakeLists.txt").write_text("project(Demo)", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/cpack")

    from vibe_code.packaging import CPackAdapter

    with pytest.raises(ValueError, match="Unsupported CPack format"):
        CPackAdapter().create_plan(
            tmp_path,
            PackageRequest("cpack", "Demo", package_type="random-installer"),
        )



def test_appimage_adapter_requires_appdir_and_uses_appimagetool(tmp_path, monkeypatch):
    appdir = tmp_path / "Demo.AppDir"
    appdir.mkdir()
    (appdir / "demo.desktop").write_text(
        "[Desktop Entry]\\nType=Application\\nName=Demo\\nExec=demo\\n",
        encoding="utf-8",
    )
    (appdir / "demo.png").write_bytes(b"png")
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/appimagetool")

    plan = AppImageAdapter().create_plan(
        tmp_path,
        PackageRequest("appimage", "Demo", entrypoint="Demo.AppDir"),
    )

    assert plan.command == (
        "/usr/bin/appimagetool",
        str(appdir),
        str(tmp_path / "dist" / "Demo.AppImage"),
    )
    assert not plan.output_dir.exists()


def test_appimage_adapter_rejects_appdir_without_desktop_file(tmp_path, monkeypatch):
    appdir = tmp_path / "Demo.AppDir"
    appdir.mkdir()
    (appdir / "demo.png").write_bytes(b"png")
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/appimagetool")

    with pytest.raises(ValueError, match=".desktop"):
        AppImageAdapter().create_plan(
            tmp_path,
            PackageRequest("appimage", "Demo", entrypoint="Demo.AppDir"),
        )


def test_packaging_engine_streams_output_and_creates_output_directory(tmp_path):
    class FakeAdapter:
        backend = "fake"

        def create_plan(self, workspace, request):
            return PackagingPlan(
                "fake",
                (sys.executable, "-c", "print('package-ok')"),
                workspace / "dist",
                "fake",
            )

    engine = PackagingEngine(tmp_path, PackagingRegistry((FakeAdapter(),)))
    plan = engine.create_plan(PackageRequest("fake", "Demo"))
    streamed = []
    result = engine.execute(
        plan, trusted_workspace=True, on_output=streamed.append
    )

    assert result.success
    assert "package-ok" in result.output
    assert "package-ok" in "".join(streamed)
    assert plan.output_dir.is_dir()


def test_packaging_engine_cancellation_stops_running_process(tmp_path):
    import threading
    import time

    class FakeAdapter:
        backend = "fake"

        def create_plan(self, workspace, request):
            script = "import time; print('started', flush=True); time.sleep(10)"
            return PackagingPlan(
                "fake", (sys.executable, "-c", script),
                workspace / "dist", "fake", timeout_seconds=30,
            )

    engine = PackagingEngine(tmp_path, PackagingRegistry((FakeAdapter(),)))
    plan = engine.create_plan(PackageRequest("fake", "Demo"))
    cancel = threading.Event()

    def receive_output(chunk):
        if "started" in chunk:
            cancel.set()

    started = time.monotonic()
    result = engine.execute(
        plan, trusted_workspace=True, cancel_event=cancel,
        on_output=receive_output,
    )

    assert not result.success
    assert "cancelled" in result.output.lower()
    assert "started" in result.output
    assert time.monotonic() - started < 5
