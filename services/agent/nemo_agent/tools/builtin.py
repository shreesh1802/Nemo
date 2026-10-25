from .base import Risk, Site, Tool, ToolRegistry
from .repo_scan import scan_repo
from .web import make_read_webpage, make_web_search

_NO_ARGS = {"type": "object", "properties": {}}


def register_builtin(registry: ToolRegistry, tavily_key: str = "") -> None:
    registry.register(
        Tool(
            name="web_search",
            description=(
                "Search the web for current or unfamiliar information (news, versions, security "
                "advisories, documentation, facts you are unsure of). Returns a short answer plus "
                "sources. Cite the source URLs you rely on."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "topic": {"type": "string", "enum": ["general", "news"]},
                    "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]},
                    "max_results": {"type": "integer", "description": "1 to 8, default 5."},
                    "depth": {"type": "string", "enum": ["basic", "advanced"], "description": "advanced is slower and deeper."},
                },
                "required": ["query"],
            },
            risk=Risk.READ,
            site=Site.SERVER,
            handler=make_web_search(tavily_key),
        )
    )
    registry.register(
        Tool(
            name="read_webpage",
            description="Read the text of one web page (a URL from search results or one the user gave).",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            risk=Risk.READ,
            site=Site.SERVER,
            handler=make_read_webpage(tavily_key),
        )
    )
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
            local_path_arg="source",
        )
    )
    # Client tools: the desktop app executes these on the user's machine, and enforces
    # which folders they may touch. The agent service never reads or writes files itself.
    def client(name, description, properties, required, risk):
        registry.register(
            Tool(
                name=name,
                description=description,
                parameters={"type": "object", "properties": properties, "required": required},
                risk=risk,
                site=Site.CLIENT,
            )
        )

    path = {"type": "string", "description": "Absolute path."}
    client("list_dir", "List the files and folders in a directory.", {"path": path}, ["path"], Risk.READ)
    client(
        "read_file",
        "Read a text file. Returns numbered lines. Always read a file before editing it.",
        {
            "path": path,
            "offset": {"type": "integer", "description": "First line to read (1-based)."},
            "limit": {"type": "integer", "description": "Maximum lines to return (default 400)."},
        },
        ["path"],
        Risk.READ,
    )
    client(
        "search_files",
        "Search file contents under a folder with a regular expression (case-insensitive).",
        {
            "path": path,
            "pattern": {"type": "string", "description": "Regular expression."},
            "glob": {"type": "string", "description": "Optional file name filter, e.g. *.py"},
        },
        ["path", "pattern"],
        Risk.READ,
    )
    client(
        "edit_file",
        "Change a file by replacing one exact piece of text with new text. old_text must appear "
        "exactly once, so include enough surrounding lines to make it unique. Prefer this over write_file.",
        {
            "path": path,
            "old_text": {"type": "string", "description": "Exact existing text, copied from read_file."},
            "new_text": {"type": "string"},
        },
        ["path", "old_text", "new_text"],
        Risk.WRITE,
    )
    client(
        "write_file",
        "Create a new file, or completely replace an existing one. Use edit_file for small changes.",
        {"path": path, "content": {"type": "string"}},
        ["path", "content"],
        Risk.WRITE,
    )
    client(
        "run_command",
        "Run a shell command (PowerShell on Windows) in a folder and return its output. Use it to run "
        "tests, install packages or use git. The user must approve every command.",
        {
            "command": {"type": "string"},
            "cwd": {"type": "string", "description": "Absolute path of the folder to run in."},
            "timeout_seconds": {"type": "integer", "description": "Default 60, maximum 300."},
        },
        ["command", "cwd"],
        Risk.DESTRUCTIVE,
    )
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
