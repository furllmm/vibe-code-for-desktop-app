from __future__ import annotations

from dataclasses import dataclass

from ..context.models import ContextPack
from ..providers.base import AgentMessage, AIProvider


@dataclass(frozen=True)
class AgentRequest:
    prompt: str
    context: ContextPack


class AgentService:
    """Build provider-neutral agent requests from user intent and selected context."""

    SYSTEM_PROMPT = (
        "You are a desktop application coding agent. "
        "Use the supplied project context as evidence, make minimal maintainable changes, "
        "and do not assume files or APIs that are not present in the context."
    )

    @classmethod
    def build_messages(cls, request: AgentRequest) -> list[AgentMessage]:
        if not request.prompt.strip():
            raise ValueError("prompt must not be empty")

        context = request.context.as_text()
        user_content = request.prompt.strip()
        if context:
            user_content += (
                "\n\n<project_context>\n"
                + context
                + "\n</project_context>"
            )

        return [
            AgentMessage(role="system", content=cls.SYSTEM_PROMPT),
            AgentMessage(role="user", content=user_content),
        ]

    @classmethod
    def complete(cls, provider: AIProvider, request: AgentRequest) -> str:
        return provider.complete(cls.build_messages(request))
