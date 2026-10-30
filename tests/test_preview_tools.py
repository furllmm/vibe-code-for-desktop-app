from pathlib import Path
import sys
import time

from vibe_code.runtime.preview import GenericPreviewAdapter, PreviewConfig, PreviewEngine
from vibe_code.tools.preview_tools import GetPreviewLogsTool, RunPreviewTool, StopPreviewTool


def make_engine(tmp_path: Path) -> PreviewEngine:
    return PreviewEngine(
        tmp_path,
        GenericPreviewAdapter(PreviewConfig((sys.executable, "-u", "-c", "print('tool-preview')"))),
    )


def test_run_preview_tool_starts_preview(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    result = RunPreviewTool(engine).execute({})
    try:
        assert result.ok
        assert engine.running
    finally:
        engine.stop()


def test_preview_log_tool_reports_exit_and_output(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    RunPreviewTool(engine).execute({})
    result = None
    for _ in range(100):
        result = GetPreviewLogsTool(engine).execute({})
        if "Preview exited" in result.output and "tool-preview" in result.output:
            break
        time.sleep(0.01)
    assert result.ok
    assert "Preview exited" in result.output
    assert "tool-preview" in result.output


def test_stop_preview_tool_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    result = StopPreviewTool(engine).execute({})
    assert result.ok
    assert "not running" in result.output
