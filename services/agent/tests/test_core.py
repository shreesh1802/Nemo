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


def test_builtin_registry_exposes_action_tools_with_the_right_risk():
    from nemo_agent.tools.builtin import register_builtin

    reg = ToolRegistry()
    register_builtin(reg)
    risk = {n: reg.get(n).risk for n in
            ("list_dir", "read_file", "search_files", "edit_file", "write_file", "run_command")}
    assert [risk[n] for n in ("list_dir", "read_file", "search_files")] == [Risk.READ] * 3
    assert risk["edit_file"] is Risk.WRITE and risk["write_file"] is Risk.WRITE
    assert risk["run_command"] is Risk.DESTRUCTIVE
    assert all(reg.get(n).site is Site.CLIENT for n in risk)  # the service never touches files itself


async def _run_edits(tmp_path, answers):
    """Drive two edit_file calls in one session; `answers` are the user's replies in order."""
    from nemo_agent.tools.builtin import register_builtin

    reg = ToolRegistry()
    register_builtin(reg)
    asked, executed = [], []
    session = None

    async def send(event):
        if event["type"] == "confirm_request":
            asked.append(event["name"])
            session.deliver({"id": event["id"], **answers.pop(0)})
        elif event["type"] == "tool_request":
            executed.append(event["name"])
            session.deliver({"id": event["id"], "ok": True, "result": "done"})

    args = json.dumps({"path": "C:/p/a.py", "old_text": "a", "new_text": "b"})
    llm = fake_llm(assistant(calls=[call("edit_file", args)]), assistant(calls=[call("edit_file", args)]), assistant("ok"))
    session = Session(llm, reg, Memory(str(tmp_path / "m.db")), send)
    await session.handle_user_message("fix it")
    return asked, executed


async def test_write_tools_ask_every_time_unless_user_allows_for_the_session(tmp_path):
    asked, executed = await _run_edits(tmp_path, [{"approved": True}, {"approved": True}])
    assert asked == ["edit_file", "edit_file"] and len(executed) == 2

    asked, executed = await _run_edits(tmp_path, [{"approved": True, "remember": True}])
    assert asked == ["edit_file"] and len(executed) == 2  # second call needed no prompt


async def test_denied_edit_never_reaches_the_desktop(tmp_path):
    asked, executed = await _run_edits(tmp_path, [{"approved": False}, {"approved": False}])
    assert executed == [] and len(asked) == 2
