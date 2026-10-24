import json
from types import SimpleNamespace
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


class MockLLM:
    """Offline stand-in used when no API key is configured, so the app can be
    developed and demoed end to end. It reads the clipboard when asked to, and
    otherwise echoes. It is not a model and is never used when a key is set."""

    @staticmethod
    def _reply(content: str | None = None, calls: list | None = None):
        msg = SimpleNamespace(content=content, tool_calls=calls)
        msg.model_dump = lambda exclude_none=True: {
            "role": "assistant",
            "content": content,
            **(
                {
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments},
                        }
                        for c in calls
                    ]
                }
                if calls
                else {}
            ),
        }
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    async def complete(self, tier, messages, tools=None):
        if tools is None:  # router call
            return self._reply('{"tier": "fast"}')
        last = messages[-1]
        if last["role"] == "tool":
            return self._reply(f"Here is what I found: {last['content'][:300]}")
        text = (last.get("content") or "").lower()
        if "clipboard" in text or "copied" in text:
            call = SimpleNamespace(
                id="mock1",
                function=SimpleNamespace(name="clipboard_read", arguments=json.dumps({})),
            )
            return self._reply(calls=[call])
        return self._reply(f"(offline mode) You said: {last.get('content')}")
