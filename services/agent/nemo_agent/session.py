import asyncio
import json
import uuid
from typing import Any, Awaitable, Callable

from .llm import LLM
from .memory import Memory
from .router import pick_tier
from .safety import Policy
from .tools.base import Site, ToolRegistry

Send = Callable[[dict[str, Any]], Awaitable[None]]

MAX_STEPS = 12
SYSTEM_PROMPT = (
    "You are Nemo, a small friendly robot living on the user's screen. "
    "Be brief; your replies are spoken aloud. Use tools when they help. "
    "If a tool is denied, accept it and offer an alternative."
)


class Session:
    """One connected desktop client: owns the conversation, loop and pending replies."""

    def __init__(self, llm: LLM, tools: ToolRegistry, memory: Memory, send: Send) -> None:
        self._llm = llm
        self._tools = tools
        self._memory = memory
        self._send = send
        self._policy = Policy()
        self._pending: dict[str, asyncio.Future] = {}
        self._history: list[dict[str, Any]] = []

    # --- inbound events from the client -----------------------------------
    def deliver(self, event: dict[str, Any]) -> None:
        """Resolve a pending tool_result or confirm event."""
        fut = self._pending.pop(event.get("id", ""), None)
        if fut and not fut.done():
            fut.set_result(event)

    async def _ask(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[event_id] = fut
        await self._send({**event, "id": event_id})
        return await fut

    # --- the loop ----------------------------------------------------------
    async def handle_user_message(self, text: str) -> None:
        try:
            await self._handle(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A failed model call must never leave the robot stuck on "thinking".
            await self._send({"type": "error", "message": f"I couldn't reach my model ({type(exc).__name__}). {str(exc)[:160]}"})
            await self._send({"type": "state", "state": "idle"})

    async def _handle(self, text: str) -> None:
        await self._send({"type": "state", "state": "thinking"})
        tier = await pick_tier(self._llm, text)
        facts = self._memory.recent()
        system = SYSTEM_PROMPT + (
            "\nKnown about the user:\n- " + "\n- ".join(facts) if facts else ""
        )
        self._history.append({"role": "user", "content": text})

        for _ in range(MAX_STEPS):
            resp = await self._llm.complete(
                tier,
                [{"role": "system", "content": system}, *self._history],
                self._tools.specs(),
            )
            msg = resp.choices[0].message
            self._history.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                await self._send({"type": "final", "text": msg.content or ""})
                await self._send({"type": "state", "state": "idle"})
                return

            await self._send({"type": "state", "state": "acting"})
            for call in msg.tool_calls:
                result = await self._run_tool(call.function.name, call.function.arguments)
                self._history.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )

        await self._send({"type": "error", "message": "Stopped: too many steps."})
        await self._send({"type": "state", "state": "idle"})

    async def _run_tool(self, name: str, raw_args: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            return json.dumps({"error": "arguments were not valid JSON"})

        if self._policy.needs_confirmation(tool):
            answer = await self._ask(
                {
                    "type": "confirm_request",
                    "name": name,
                    "args": args,
                    "risk": tool.risk.value,
                }
            )
            if not answer.get("approved"):
                return json.dumps({"error": "user denied this action"})
            self._policy.record_approval(tool)

        try:
            if tool.site is Site.CLIENT:
                answer = await self._ask({"type": "tool_request", "name": name, "args": args})
                if not answer.get("ok"):
                    return json.dumps({"error": answer.get("result", "tool failed")})
                result = answer.get("result")
            else:
                result = await tool.handler(args)  # type: ignore[misc]
        except Exception as exc:  # a failing tool must not kill the conversation
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return result if isinstance(result, str) else json.dumps(result)
