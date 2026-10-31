from pathlib import Path

from vibe_code.agent.service import AgentLoop, AgentRequest
from vibe_code.context.models import ContextPack
from vibe_code.providers.base import ProviderResponse, ToolCall
from vibe_code.runtime.preview import GenericPreviewAdapter, PreviewConfig, PreviewEngine
from vibe_code.tools.preview_tools import GetPreviewLogsTool, RunPreviewTool
from vibe_code.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self):
        self.requests = []
        self.calls = [
            ProviderResponse("", (ToolCall("1", "run_preview", {}),)),
            ProviderResponse("", (ToolCall("2", "get_preview_logs", {}),)),
            ProviderResponse("done"),
        ]

    def complete(self, request):
        self.requests.append(request)
        return self.calls.pop(0)


def test_agent_can_run_and_inspect_preview(tmp_path: Path) -> None:
    engine = PreviewEngine(
        tmp_path,
        GenericPreviewAdapter(PreviewConfig(("python", "-c", "print('agent-preview')"))),
    )
    registry = ToolRegistry((RunPreviewTool(engine), GetPreviewLogsTool(engine)))
    provider = FakeProvider()
    result = AgentLoop(provider, registry).run(AgentRequest("test", ContextPack((), 0)))

    try:
        assert result.content == "done"
        assert [x.name for x in result.executions] == ["run_preview", "get_preview_logs"]
        assert len(provider.requests) == 3
        assert provider.requests[1].messages[-1].role == "tool"
    finally:
        engine.stop()