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

MAX_STEPS = 25
SYSTEM_PROMPT = (
    "You are Nemo, a small friendly assistant living on the user's screen. Keep replies short. "
    "Do exactly what the user asked and nothing more. Scanning, reading, explaining or answering is "
    "never a request to change anything: report what you found and offer to fix it, then wait. "
    "Never install software or change files or settings that the user did not ask you to. "
    "You can act on the user's computer with your tools. When asked to fix, change, create, "
    "install or run something, do it yourself instead of listing steps for the user to follow. "
    "Work like this: look first (list_dir, search_files, read_file), then make the smallest change "
    "that works (edit_file), then check it (run_command, for example the tests). Always read a file "
    "before editing it, and read the code that a failing test or error points at before deciding what is "
    "wrong. Run tests with the real test runner (for Python use `python -m pytest`, for Node `npm test`) "
    "and read its output; a command that prints nothing may not have tested anything, so never report "
    "success without evidence. Use absolute paths. The user approves every change and command and sees exactly "
    "what you intend to do, so do not ask for permission in words. If the user denies something, do not "
    "retry the same thing; offer an alternative or ask what they prefer. When you finish, say briefly "
    "what you changed and what you verified."
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
            if answer.get("remember"):  # "Allow for this session"; destructive tools ignore it
                self._policy.record_approval(tool)

        try:
            if tool.local_path_arg:
                target = str(args.get(tool.local_path_arg, "")).strip()
                if target and not target.startswith(("http://", "https://")):
                    # The service is about to read the user's disk: the desktop app must
                    # approve this folder first, exactly as it does for its own file tools.
                    check = await self._ask(
                        {"type": "tool_request", "name": "check_access", "args": {"path": target}}
                    )
                    if not check.get("ok"):
                        return json.dumps({"error": check.get("result") or "access to that folder was not allowed"})
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
