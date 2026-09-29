from pathlib import Path

from vibe_code.runtime.preview import GenericPreviewAdapter, PreviewConfig, PreviewEngine
from vibe_code.runtime.process import ProcessManager


def test_process_manager_captures_output_and_exit(tmp_path: Path) -> None:
    manager = ProcessManager(tmp_path)
    manager.start(("python", "-c", "print('hello')"))
    result = None
    for _ in range(100):
        result = manager.poll()
        if result is not None:
            break
    assert result is not None
    assert result.returncode == 0
    assert not result.crashed
    assert "hello" in manager.read_available()


def test_process_manager_rejects_empty_command(tmp_path: Path) -> None:
    manager = ProcessManager(tmp_path)
    try:
        manager.start(())
    except ValueError as exc:
        assert "command" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_preview_engine_restart_and_stop(tmp_path: Path) -> None:
    adapter = GenericPreviewAdapter(
        PreviewConfig(("python", "-c", "print('preview')"))
    )
    engine = PreviewEngine(tmp_path, adapter)
    engine.build()
    engine.start()
    assert engine.process.running
    engine.restart()
    assert engine.process.running
    engine.stop()
    assert not engine.process.running
