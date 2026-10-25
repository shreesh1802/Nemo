import json
import re

from .llm import LLM

_PROMPT = (
    "Classify the user's request for a desktop assistant. Reply with JSON only: "
    '{"tier": "fast" | "standard" | "deep"}. '
    "fast = a simple lookup, a rewrite, or one quick action. "
    "standard = a task needing a few tool calls. "
    "deep = multi-step analysis, security review, planning, or hard reasoning."
)


async def pick_tier(llm: LLM, text: str) -> str:
    try:
        resp = await llm.complete(
            "fast",
            [{"role": "system", "content": _PROMPT}, {"role": "user", "content": text}],
        )
        raw = resp.choices[0].message.content or ""
        match = re.search(r"\{.*?\}", raw, re.S)  # tolerate code fences around the JSON
        tier = json.loads(match.group(0) if match else "{}").get("tier")
        if tier in ("fast", "standard", "deep"):
            return tier
    except Exception:
        pass  # routing is an optimisation; never block a request on it
    return "standard"
