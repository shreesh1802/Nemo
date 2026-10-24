from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


class Risk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class Site(str, Enum):
    CLIENT = "client"  # executed by the desktop app on the user's machine
    SERVER = "server"  # executed by this service


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments
    risk: Risk
    site: Site
    handler: Callable[[dict[str, Any]], Awaitable[Any]] | None = None  # server tools only
    tags: list[str] = field(default_factory=list)

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        if tool.site is Site.SERVER and tool.handler is None:
            raise ValueError(f"server tool needs a handler: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        return [t.as_openai() for t in self._tools.values()]
