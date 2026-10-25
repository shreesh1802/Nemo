"""Claude provider: a stand-in model while Nemotron credits are pending.

Uses the official Anthropic SDK and presents the same `complete(tier, messages,
tools)` interface as the Token Factory client, returning OpenAI-shaped objects
so the session loop works unchanged. Conversation history stays in the loop's
OpenAI-style format; this module translates at the boundary.
"""
import json
from types import SimpleNamespace
from typing import Any

import anthropic

# tier -> (model, effort). Effort replaces thinking budgets on these models.
TIERS = {
    "fast": ("claude-haiku-5-5", "low"),
    "standard": ("claude-sonnet-5-5", "medium"),
    "deep": ("claude-opus-5-5", "high"),
}
MAX_TOKENS = 16000


def to_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Translate loop-format messages into (system, anthropic messages)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            if m.get("_blocks"):
                # Replay exactly what the model produced, thinking blocks included.
                out.append({"role": "assistant", "content": m["_blocks"]})
                continue
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for call in m.get("tool_calls") or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"] or "{}"),
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            result = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            last = out[-1] if out else None
            if (
                last
                and last["role"] == "user"
                and isinstance(last["content"], list)
                and all(b.get("type") == "tool_result" for b in last["content"])
            ):
                last["content"].append(result)  # parallel results share one user turn
            else:
                out.append({"role": "user", "content": [result]})
    return system, out


def tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


def to_completion(response) -> SimpleNamespace:
    """Wrap an Anthropic response in the OpenAI-shaped object the loop expects."""
    if response.stop_reason == "refusal":
        return _wrap("Sorry, I can't help with that one.", [], [])
    blocks = [b.model_dump(exclude_none=True) for b in response.content]
    text = "".join(b.text for b in response.content if b.type == "text")
    calls = [
        SimpleNamespace(
            id=b.id,
            function=SimpleNamespace(name=b.name, arguments=json.dumps(b.input)),
        )
        for b in response.content
        if b.type == "tool_use"
    ]
    return _wrap(text or None, calls, blocks)


def _wrap(text, calls, blocks) -> SimpleNamespace:
    msg = SimpleNamespace(content=text, tool_calls=calls or None)

    def dump(exclude_none: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"role": "assistant", "content": text}
        if calls:
            out["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ]
        if blocks:
            out["_blocks"] = blocks
        return out

    msg.model_dump = dump
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class AnthropicLLM:
    def __init__(self) -> None:
        # Zero-arg client resolves ANTHROPIC_API_KEY from the environment.
        self._client = anthropic.AsyncAnthropic()

    async def complete(self, tier: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None):
        model, effort = TIERS[tier]
        system, converted = to_anthropic(messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": converted,
            "output_config": {"effort": effort},
        }
        if tools:
            kwargs["tools"] = tools_to_anthropic(tools)
        return to_completion(await self._client.messages.create(**kwargs))
