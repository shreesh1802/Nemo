from .base import Risk, Site, Tool, ToolRegistry
from .repo_scan import scan_repo

_NO_ARGS = {"type": "object", "properties": {}}


def register_builtin(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="scan_repo",
            description=(
                "Security-scan a code repository for hardcoded secrets, risky code patterns and "
                "dependencies with known CVEs. `source` is a local folder path or an https git URL. "
                "Returns findings sorted by severity; explain the most important ones and how to fix them."
            ),
            parameters={
                "type": "object",
                "properties": {"source": {"type": "string"}},
                "required": ["source"],
            },
            risk=Risk.READ,
            site=Site.SERVER,
            handler=scan_repo,
        )
    )
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
