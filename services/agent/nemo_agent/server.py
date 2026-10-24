import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import load_settings
from .llm import LLM, MockLLM
from .memory import Memory
from .session import Session
from .tools.base import ToolRegistry
from .tools.builtin import register_builtin

app = FastAPI(title="Nemo agent")
settings = load_settings()
# Without a key the agent runs in offline mock mode so the app is still usable.
llm = LLM(settings) if settings.api_key and settings.model_for("standard") else MockLLM()
memory = Memory(settings.db_path)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin(registry)
    return registry


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


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
