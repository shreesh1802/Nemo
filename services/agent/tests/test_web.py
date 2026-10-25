import json

import httpx
import pytest

from nemo_agent.tools import web
from nemo_agent.tools.base import Risk, Site, ToolRegistry
from nemo_agent.tools.builtin import register_builtin


def fake_tavily(monkeypatch, handler):
    """Replace the network with a function (request) -> response."""
    seen = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(web, "_transport", httpx.MockTransport(wrapped))
    return seen


async def test_search_returns_trimmed_sources_and_marks_them_untrusted(monkeypatch):
    long = "word " * 400
    seen = fake_tavily(monkeypatch, lambda r: httpx.Response(200, json={
        "answer": "Electron 33 is current.",
        "results": [{"title": "Electron", "url": "https://electronjs.org", "content": long, "score": 0.9}],
    }))
    out = await web.make_web_search("tvly-key")({"query": "latest electron version"})
    assert out["answer"] == "Electron 33 is current."
    assert out["results"][0]["url"] == "https://electronjs.org"
    assert len(out["results"][0]["snippet"]) <= web.MAX_SNIPPET + 3
    assert "Untrusted" in out["notice"]
    req = seen[0]
    assert req.url.path == "/search" and req.headers["authorization"] == "Bearer tvly-key"
    body = json.loads(req.content)
    assert body["query"] == "latest electron version" and body["max_results"] == 5


async def test_search_options_are_validated_and_clamped(monkeypatch):
    seen = fake_tavily(monkeypatch, lambda r: httpx.Response(200, json={"results": []}))
    await web.make_web_search("k")({"query": "x", "max_results": 99, "topic": "bogus", "time_range": "decade", "depth": "advanced"})
    body = json.loads(seen[0].content)
    assert body["max_results"] == 8 and body["topic"] == "general"
    assert "time_range" not in body and body["search_depth"] == "advanced"


async def test_search_errors_come_back_as_messages_not_exceptions(monkeypatch):
    search = web.make_web_search("k")
    fake_tavily(monkeypatch, lambda r: httpx.Response(401, json={}))
    assert "rejected the API key" in (await search({"query": "x"}))["error"]
    fake_tavily(monkeypatch, lambda r: httpx.Response(429, json={}))
    assert "rate limit" in (await search({"query": "x"}))["error"]
    fake_tavily(monkeypatch, lambda r: httpx.Response(500, json={}))
    assert "500" in (await search({"query": "x"}))["error"]

    def boom(request):
        raise httpx.ConnectError("offline")

    fake_tavily(monkeypatch, boom)
    assert "Could not reach Tavily" in (await search({"query": "x"}))["error"]
    assert "required" in (await search({"query": "  "}))["error"]


async def test_missing_key_explains_how_to_fix_it():
    out = await web.make_web_search("")({"query": "x"})
    assert "TAVILY_API_KEY" in out["error"]


async def test_read_webpage_extracts_and_truncates(monkeypatch):
    seen = fake_tavily(monkeypatch, lambda r: httpx.Response(200, json={
        "results": [{"url": "https://example.com/a", "raw_content": "x" * 20000}]}))
    out = await web.make_read_webpage("k")({"url": "https://example.com/a"})
    assert len(out["content"]) <= web.MAX_PAGE + 3 and "Untrusted" in out["notice"]
    assert seen[0].url.path == "/extract"
    assert json.loads(seen[0].content)["urls"] == ["https://example.com/a"]


async def test_read_webpage_only_accepts_web_urls(monkeypatch):
    seen = fake_tavily(monkeypatch, lambda r: httpx.Response(200, json={}))
    for bad in ("file:///C:/Windows/win.ini", "ftp://x/y", "C:\\secrets.txt", ""):
        assert "error" in await web.make_read_webpage("k")({"url": bad})
    assert seen == []  # nothing was even sent


async def test_unreadable_page_reports_an_error(monkeypatch):
    fake_tavily(monkeypatch, lambda r: httpx.Response(200, json={"results": [], "failed_results": [{"url": "u"}]}))
    assert "error" in await web.make_read_webpage("k")({"url": "https://example.com"})


def test_web_tools_are_registered_as_read_only_server_tools():
    reg = ToolRegistry()
    register_builtin(reg, "key")
    for name in ("web_search", "read_webpage"):
        tool = reg.get(name)
        assert tool.risk is Risk.READ and tool.site is Site.SERVER and tool.local_path_arg is None
