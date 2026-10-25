import json
from types import SimpleNamespace

from nemo_agent.llm_anthropic import to_anthropic, to_completion, tools_to_anthropic
from nemo_agent.memory import Memory
from nemo_agent.session import Session
from nemo_agent.tools.base import ToolRegistry


def block(type_, **kw):
    b = SimpleNamespace(type=type_, **kw)
    b.model_dump = lambda exclude_none=True: {"type": type_, **kw}
    return b


def test_history_translation_groups_parallel_tool_results():
    call = lambda i, n: {"id": i, "type": "function", "function": {"name": n, "arguments": "{}"}}
    system, out = to_anthropic(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [call("a", "x"), call("b", "y")]},
            {"role": "tool", "tool_call_id": "a", "content": "1"},
            {"role": "tool", "tool_call_id": "b", "content": "2"},
        ]
    )
    assert system == "be brief"
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["type"] for b in out[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"]  # one user turn


def test_assistant_blocks_replayed_verbatim_including_thinking():
    blocks = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "ok"}]
    _, out = to_anthropic([{"role": "assistant", "content": "ok", "_blocks": blocks}])
    assert out[0]["content"] == blocks


def test_tools_translation():
    spec = [{"type": "function", "function": {"name": "t", "description": "d", "parameters": {"type": "object"}}}]
    assert tools_to_anthropic(spec) == [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]


def test_completion_extracts_text_and_tool_calls_and_keeps_blocks():
    resp = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            block("thinking", thinking="", signature="s"),
            block("text", text="checking"),
            block("tool_use", id="tu1", name="scan_repo", input={"source": "."}),
        ],
    )
    msg = to_completion(resp).choices[0].message
    assert msg.content == "checking"
    assert msg.tool_calls[0].function.name == "scan_repo"
    assert json.loads(msg.tool_calls[0].function.arguments) == {"source": "."}
    dumped = msg.model_dump(exclude_none=True)
    assert dumped["_blocks"][0]["type"] == "thinking" and dumped["tool_calls"][0]["id"] == "tu1"


def test_refusal_becomes_a_polite_answer():
    resp = SimpleNamespace(stop_reason="refusal", content=[])
    msg = to_completion(resp).choices[0].message
    assert msg.tool_calls is None and "can't help" in msg.content


async def test_model_failure_reports_error_instead_of_hanging(tmp_path):
    class Boom:
        async def complete(self, *a, **k):
            raise RuntimeError("no credits")

    sent = []

    async def send(event):
        sent.append(event)

    session = Session(Boom(), ToolRegistry(), Memory(str(tmp_path / "m.db")), send)
    await session.handle_user_message("hi")
    assert any(e["type"] == "error" and "no credits" in e["message"] for e in sent)
    assert sent[-1] == {"type": "state", "state": "idle"}
