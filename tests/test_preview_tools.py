from pathlib import Path

from vibe_code.runtime.preview import GenericPreviewAdapter, PreviewConfig, PreviewEngine
from vibe_code.tools.preview_tools import GetPreviewLogsTool, RunPreviewTool, StopPreviewTool


def make_engine(tmp_path: Path) -> PreviewEngine:
    return PreviewEngine(
        tmp_path,
        GenericPreviewAdapter(PreviewConfig(("python", "-c", "print('tool-preview')"))),
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
    for _ in range(100):
        result = GetPreviewLogsTool(engine).execute({})
        if "Preview exited" in result.output:
            break
    assert result.ok
    assert "tool-preview" in result.output


def test_stop_preview_tool_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    result = StopPreviewTool(engine).execute({})
    assert result.ok
    assert "not running" in result.output
