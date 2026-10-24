import json
from types import SimpleNamespace

import pytest

from nemo_agent.memory import Memory
from nemo_agent.safety import Policy
from nemo_agent.session import Session
from nemo_agent.tools.base import Risk, Site, Tool, ToolRegistry


def make_tool(name="t", risk=Risk.READ, site=Site.SERVER, handler=None):
    async def default(_args):
        return {"ok": True}

    return Tool(name, "d", {"type": "object", "properties": {}}, risk, site, handler or default)


def test_policy_levels():
    p = Policy()
    assert not p.needs_confirmation(make_tool(risk=Risk.READ))
    write = make_tool(risk=Risk.WRITE)
    assert p.needs_confirmation(write)
    p.record_approval(write)
    assert not p.needs_confirmation(write)
    destructive = make_tool(risk=Risk.DESTRUCTIVE)
    p.record_approval(destructive)
    assert p.needs_confirmation(destructive)  # never remembered


def test_registry_rejects_duplicates_and_handlerless_server_tools():
    reg = ToolRegistry()
    reg.register(make_tool("a"))
    with pytest.raises(ValueError):
        reg.register(make_tool("a"))
    with pytest.raises(ValueError):
        reg.register(Tool("b", "d", {}, Risk.READ, Site.SERVER))


def fake_llm(*messages):
    """LLM stub that returns the given assistant messages in order."""
    queue = list(messages)

    class Stub:
        async def complete(self, tier, msgs, tools=None):
            if tier == "fast" and tools is None:
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"tier":"fast"}'))]
                )
            return SimpleNamespace(choices=[SimpleNamespace(message=queue.pop(0))])

    return Stub()


def assistant(content=None, calls=None):
    msg = SimpleNamespace(content=content, tool_calls=calls)
    msg.model_dump = lambda exclude_none=True: {"role": "assistant", "content": content}
    return msg


def call(name, args="{}"):
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=args))


async def test_loop_runs_server_tool_then_answers(tmp_path):
    reg = ToolRegistry()
    reg.register(make_tool("lookup"))
    sent = []

    async def send(event):
        sent.append(event)

    llm = fake_llm(assistant(calls=[call("lookup")]), assistant("done"))
    session = Session(llm, reg, Memory(str(tmp_path / "m.db")), send)
    await session.handle_user_message("hi")
    assert {"type": "final", "text": "done"} in sent


async def test_destructive_tool_is_blocked_when_user_denies(tmp_path):
    ran = []

    async def handler(_args):
        ran.append(1)
        return "x"

    reg = ToolRegistry()
    reg.register(make_tool("rm", Risk.DESTRUCTIVE, handler=handler))
    sent = []
    session = None

    async def send(event):
        sent.append(event)
        if event["type"] == "confirm_request":
            session.deliver({"id": event["id"], "approved": False})

    llm = fake_llm(assistant(calls=[call("rm")]), assistant("ok"))
    session = Session(llm, reg, Memory(str(tmp_path / "m.db")), send)
    await session.handle_user_message("delete it")
    assert not ran
    assert any(e["type"] == "confirm_request" for e in sent)
