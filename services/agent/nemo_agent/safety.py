from .tools.base import Risk, Tool


class Policy:
    """Decides whether a tool call needs the user's explicit confirmation.

    The model never gets a vote: this runs in code between the model's request
    and the tool's execution.
    """

    def __init__(self) -> None:
        self._approved_for_session: set[str] = set()

    def needs_confirmation(self, tool: Tool) -> bool:
        if tool.risk is Risk.READ:
            return False
        if tool.risk is Risk.WRITE:
            return tool.name not in self._approved_for_session
        return True  # destructive: always ask

    def record_approval(self, tool: Tool) -> None:
        # Only write-level approvals are remembered; destructive ones never are.
        if tool.risk is Risk.WRITE:
            self._approved_for_session.add(tool.name)
