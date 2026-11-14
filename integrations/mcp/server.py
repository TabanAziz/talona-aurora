"""The MCP server: four tools over stdio that answer from the Aurora HTTP API and never change the site.

    uv run --project integrations/mcp python integrations/mcp/server.py

An MCP host launches this file as a subprocess and talks JSON-RPC over its stdin and stdout. Every tool is a thin
wrapper over tools.py, so the tests can call the same functions without a host.
"""
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import tools

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
RECORDS_ONLY = ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False,
                               idempotent_hint=False)

mcp = MCPServer(
    "Aurora site state",
    instructions="Read-only questions about the Maple Court site record. can_start answers whether a task may "
                 "start and never answers yes when Aurora cannot be reached.",
)


@mcp.tool(annotations=READ_ONLY)
def site_state() -> dict:
    """Project name, open flag and waiting counts, and the tasks planned for today and tomorrow."""
    return tools.site_state()


@mcp.tool(annotations=READ_ONLY)
def open_flags() -> dict:
    """Every open or held flag with its id, type, title, work start, affected unit or crew and status."""
    return tools.open_flags()


@mcp.tool(annotations=READ_ONLY)
def waiting_on() -> dict:
    """Who owes what, since when and until when, with the events that opened each waiting item."""
    return tools.waiting_on()


@mcp.tool(annotations=RECORDS_ONLY)
def can_start(asked_by: str, task_id: str | None = None, unit: str | None = None,
              activity: str | None = None) -> dict:
    """May this task start now, and why?

    Give task_id, or unit plus activity such as open walls. The answer has the verdict (yes, no, unknown), a
    sentence, and the reasons with the source event ids. It records the check in the site record and changes no
    work. When Aurora cannot be reached it answers unknown, never yes.
    """
    return tools.can_start(asked_by=asked_by, task_id=task_id, unit=unit, activity=activity)


if __name__ == "__main__":
    mcp.run()
