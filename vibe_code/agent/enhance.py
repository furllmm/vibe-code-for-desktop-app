from __future__ import annotations

from ..context.models import ContextPack
from ..providers.base import AgentMessage, AIProvider, ProviderRequest


class EnhancementService:
    """Turn a rough request into a detailed brief without executing the task."""

    SYSTEM_PROMPT = """You are a senior product-minded desktop software engineer and UX designer.
Rewrite the user's rough request as a clear, detailed implementation brief tailored to the supplied project context.

Rules:
- Preserve the user's intent and explicit choices; do not silently replace them with your own preferences.
- Separate requested requirements from optional suggestions. Never present suggestions as user-approved requirements.
- Be specific and actionable, but do not invent existing files, APIs, dependencies, or capabilities.
- Prefer the project's current architecture, design language, and dependencies; avoid unnecessary rewrites.
- Include relevant behavior, UX states, accessibility, error handling, security, tests, and acceptance criteria.
- Call out genuinely important ambiguity or risk briefly; do not ask a long list of questions.
- Do not write or modify code. Return only the enhanced brief with concise headings."""

    @classmethod
    def build_request(cls, prompt: str, context: ContextPack) -> ProviderRequest:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        content = prompt.strip()
        project_context = context.as_text()
        if project_context:
            content += "\n\n<project_context>\n" + project_context + "\n</project_context>"
        return ProviderRequest(
            messages=(
                AgentMessage(role="system", content=cls.SYSTEM_PROMPT),
                AgentMessage(
                    role="user",
                    content=(
                        "Enhance this request into a practical implementation brief. "
                        "Keep user intent intact and distinguish optional suggestions.\n\n"
                        + content
                    ),
                ),
            ),
            tools=(),
        )

    @classmethod
    def enhance(cls, provider: AIProvider, prompt: str, context: ContextPack) -> str:
        response = provider.complete(cls.build_request(prompt, context))
        return response.content.strip()
