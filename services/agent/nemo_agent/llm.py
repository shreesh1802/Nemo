from typing import Any

from openai import AsyncOpenAI

from .config import Settings


class LLM:
    """Thin wrapper over Token Factory's OpenAI-compatible API, addressed by tier."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)

    async def complete(
        self,
        tier: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        kwargs: dict[str, Any] = {
            "model": self._settings.model_for(tier),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return await self._client.chat.completions.create(**kwargs)
