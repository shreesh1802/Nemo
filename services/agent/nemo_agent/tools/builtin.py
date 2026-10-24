from .base import Risk, Site, Tool, ToolRegistry

_NO_ARGS = {"type": "object", "properties": {}}


def register_builtin(registry: ToolRegistry) -> None:
    # Client tools: the desktop app executes these on the user's machine.
    registry.register(
        Tool(
            name="clipboard_read",
            description="Read the text currently on the user's clipboard.",
            parameters=_NO_ARGS,
            risk=Risk.READ,
            site=Site.CLIENT,
        )
    )
    registry.register(
        Tool(
            name="clipboard_write",
            description="Replace the user's clipboard with the given text.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            risk=Risk.WRITE,
            site=Site.CLIENT,
        )
    )
