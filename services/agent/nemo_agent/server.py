import asyncio
import logging
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import load_settings
from .llm import LLM, MockLLM
from .memory import Memory
from .session import Session
from .tools.base import ToolRegistry
from .tools.builtin import register_builtin

log = logging.getLogger("uvicorn.error")
app = FastAPI(title="Nemo agent")
settings = load_settings()


def build_llm():
    """Pick the model provider. Set NEMO_PROVIDER=nebius|claude|mock to force one;
    otherwise Nebius is used when configured, then Claude, then the offline mock."""
    forced = os.getenv("NEMO_PROVIDER", "").strip().lower()
    nebius_ready = bool(settings.api_key and settings.model_for("standard"))
    if forced == "claude" or (not forced and not nebius_ready and os.getenv("ANTHROPIC_API_KEY")):
        from .llm_anthropic import AnthropicLLM

        return "claude", AnthropicLLM()
    if forced == "nebius" or (not forced and nebius_ready):
        return "nebius", LLM(settings)
    return "mock", MockLLM()  # no keys: the app still runs offline


provider, llm = build_llm()
log.info("Nemo model provider: %s", provider)
memory = Memory(settings.db_path)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin(registry)
    return registry


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "provider": provider}


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    session = Session(llm, build_registry(), memory, socket.send_json)
    tasks: set[asyncio.Task] = set()
    try:
        while True:
            event = await socket.receive_json()
            kind = event.get("type")
            if kind == "user_message":
                # Run as a task so tool_result / confirm events can still arrive.
                task = asyncio.create_task(session.handle_user_message(event["text"]))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            elif kind in ("tool_result", "confirm"):
                session.deliver(event)
    except WebSocketDisconnect:
        for task in tasks:
            task.cancel()
