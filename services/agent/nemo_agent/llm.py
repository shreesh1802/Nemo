import json
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI, NotFoundError, PermissionDeniedError

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
        kwargs: dict[str, Any] = {"messages": messages}
        if tools:
            kwargs["tools"] = tools
        # A tier whose model this account can't use falls back to the next tier down,
        # so one unavailable model never makes the whole agent unusable.
        chain = {"deep": ["deep", "standard", "fast"], "standard": ["standard", "fast"], "fast": ["fast"]}[tier]
        tried: set[str] = set()
        last_error: Exception | None = None
        for step in chain:
            model = self._settings.model_for(step)
            if model in tried:
                continue
            tried.add(model)
            try:
                return await self._client.chat.completions.create(model=model, **kwargs)
            except (NotFoundError, PermissionDeniedError) as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]


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
            return self._reply(self._explain(last["content"]))
        text = (last.get("content") or "").lower()
        if "scan" in text:
            words = [w for w in (last.get("content") or "").split() if "/" in w or "\\" in w]
            call = SimpleNamespace(
                id="mock2",
                function=SimpleNamespace(
                    name="scan_repo", arguments=json.dumps({"source": words[0] if words else "."})
                ),
            )
            return self._reply(calls=[call])
        if "clipboard" in text or "copied" in text:
            call = SimpleNamespace(
                id="mock1",
                function=SimpleNamespace(name="clipboard_read", arguments=json.dumps({})),
            )
            return self._reply(calls=[call])
        return self._reply(
            f"I heard \"{last.get('content')}\". I can't reason about that just yet, "
            "but I can read your clipboard or scan a repo for security problems."
        )

    @staticmethod
    def _explain(raw: str) -> str:
        """Turn a tool result into a short, friendly sentence."""
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = raw
        if isinstance(data, dict) and "error" in data:
            return f"That didn't work: {data['error']}."
        if isinstance(data, dict) and "counts" in data:
            c, total = data["counts"], data["total"]
            if not total:
                return f"All clear. I checked {data['files_scanned']} files and found nothing worrying."
            parts = [f"{c[s]} {s}" for s in ("critical", "high", "medium", "low") if c[s]]
            top = data["findings"][0]
            where = f"{top['file']}" + (f":{top['line']}" if top["line"] else "")
            return (
                f"I looked through {data['files_scanned']} files and found {total} "
                f"issue{'s' if total != 1 else ''} ({', '.join(parts)}). "
                f"The most serious is in {where}: {top['message']} {top['fix']}"
            )
        text = data if isinstance(data, str) else json.dumps(data)
        text = text.strip()
        if not text:
            return "Your clipboard looks empty."
        shown = text if len(text) <= 240 else text[:240] + "..."
        return f"Your clipboard says: \"{shown}\""
