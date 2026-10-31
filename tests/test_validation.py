import sys

import pytest

from vibe_code.runtime.process import ProcessResult
from vibe_code.runtime.validation import ProjectValidator


class FakePreview:
    def __init__(self, workspace, *, build_error=None, start_error=None, status=None):
        self.workspace = workspace.resolve()
        self.build_error = build_error
        self.start_error = start_error
        self.status = status
        self.running = False
        self.calls = []

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def build(self):
        self.calls.append("build")
        if self.build_error:
            raise RuntimeError(self.build_error)

    def start(self):
        self.calls.append("start")
        if self.start_error:
            raise RuntimeError(self.start_error)
        self.running = self.status is None

    def poll(self):
        self.calls.append("poll")
        if self.status is not None:
            self.running = False
            return self.status
        return None

    def read_logs(self):
        return "preview output\n"


def test_python_tests_build_and_preview_success(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    calls = []

    class Completed:
        returncode = 0
        stdout = "2 passed"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["shell"] is False
        assert kwargs["cwd"] == tmp_path.resolve()
        return Completed()

    monkeypatch.setattr("vibe_code.runtime.validation.subprocess.run", fake_run)
    preview = FakePreview(tmp_path)
    result = ProjectValidator(tmp_path, preview, startup_timeout=0.001).run()

    assert result.success
    assert result.preview_running
    assert calls[0][0] == [sys.executable, "-m", "pytest", "-q"]
    assert [step.name for step in result.steps] == ["Tests", "Build", "Preview smoke check"]
    assert preview.calls[:3] == ["stop", "build", "start"]


def test_test_failure_stops_before_build_or_preview(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("module example\n")

    class Completed:
        returncode = 1
        stdout = "test failed"

    monkeypatch.setattr(
        "vibe_code.runtime.validation.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    preview = FakePreview(tmp_path)
    result = ProjectValidator(tmp_path, preview).run()

    assert not result.success
    assert "test failed" in result.output
    assert "build" not in preview.calls
    assert "start" not in preview.calls


def test_missing_test_runner_is_a_validation_failure(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text('[package]\nname="demo"\nversion="0.1.0"\n')
    def missing(*args, **kwargs):
        raise FileNotFoundError
    monkeypatch.setattr("vibe_code.runtime.validation.subprocess.run", missing)
    preview = FakePreview(tmp_path)
    result = ProjectValidator(tmp_path, preview).run()
    assert not result.success
    assert "cargo" in result.output
    assert "build" not in preview.calls


def test_build_failure_prevents_preview_start(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("module example\n")
    class Completed:
        returncode = 0
        stdout = "ok"
    monkeypatch.setattr(
        "vibe_code.runtime.validation.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    preview = FakePreview(tmp_path, build_error="compiler error")
    result = ProjectValidator(tmp_path, preview).run()
    assert not result.success
    assert "compiler error" in result.output
    assert "start" not in preview.calls


def test_preview_nonzero_exit_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "vibe_code.runtime.validation.subprocess.run",
        lambda *args, **kwargs: pytest.fail("no test command expected"),
    )
    preview = FakePreview(tmp_path, status=ProcessResult(3, True))
    result = ProjectValidator(tmp_path, preview, startup_timeout=0.001).run()
    assert not result.success
    assert "Exit code: 3" in result.output


def test_clean_preview_exit_is_not_a_crash(tmp_path, monkeypatch):
    preview = FakePreview(tmp_path, status=ProcessResult(0, False))
    result = ProjectValidator(tmp_path, preview, startup_timeout=0.001).run()
    assert result.success
    assert not result.preview_running


def test_unknown_project_skips_tests_but_builds_and_checks_preview(tmp_path, monkeypatch):
    preview = FakePreview(tmp_path, status=ProcessResult(0, False))
    result = ProjectValidator(tmp_path, preview, startup_timeout=0.001).run()
    assert result.success
    assert result.steps[0].skipped
    assert "skipped" in result.steps[0].output.lower()


def test_validator_rejects_preview_from_another_workspace(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="different workspace"):
        ProjectValidator(tmp_path, FakePreview(other))


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ("Cargo.toml", "cargo"),
        ("go.mod", "go"),
        ("pom.xml", "mvn"),
        ("build.gradle", "gradle"),
    ],
)
def test_language_test_command_detection(tmp_path, manifest, expected):
    (tmp_path / manifest).write_text("placeholder")
    validator = ProjectValidator(tmp_path, FakePreview(tmp_path))
    assert validator._test_command()[0] == expected


def test_node_test_script_is_detected(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"node test.js"}}', encoding="utf-8"
    )
    validator = ProjectValidator(tmp_path, FakePreview(tmp_path))
    assert validator._test_command() == ("npm", "test")


def test_validator_requires_positive_timeouts(tmp_path):
    with pytest.raises(ValueError, match="timeouts"):
        ProjectValidator(tmp_path, FakePreview(tmp_path), test_timeout=0)

def test_cmake_ctest_is_scheduled_after_successful_build(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("include(CTest)\n")
    commands = []

    class Completed:
        returncode = 0
        stdout = "all tests passed"

    monkeypatch.setattr(
        "vibe_code.runtime.validation.subprocess.run",
        lambda command, **kwargs: (commands.append(command) or Completed()),
    )
    preview = FakePreview(tmp_path, status=ProcessResult(0, False))
    result = ProjectValidator(tmp_path, preview, startup_timeout=0.001).run()

    assert result.success
    assert commands == [[
        "ctest", "--test-dir",
        str(tmp_path.resolve() / ".vibe-code" / "build" / "cmake"),
        "--output-on-failure",
    ]]
    assert [step.name for step in result.steps] == [
        "Tests", "Build", "Build-system tests", "Preview smoke check"
    ]


def test_cmake_test_failure_prevents_preview_start(tmp_path, monkeypatch):
    (tmp_path / "CMakeLists.txt").write_text("enable_testing()\n")

    class Completed:
        returncode = 8
        stdout = "CTest failed"

    monkeypatch.setattr(
        "vibe_code.runtime.validation.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    preview = FakePreview(tmp_path)
    result = ProjectValidator(tmp_path, preview).run()

    assert not result.success
    assert "CTest failed" in result.output
    assert "start" not in preview.calls
