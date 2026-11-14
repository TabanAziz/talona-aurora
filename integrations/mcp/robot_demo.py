"""A scripted layout robot: it asks Aurora whether it may start, and starts only when the answer is yes.

    uv run --project integrations/mcp python integrations/mcp/robot_demo.py

The robot talks to the MCP server the way a real host does, over stdio, and the server asks the Aurora API. There
is no model anywhere in this path: the answer comes from the record. The exit code is 0 when the robot starts and
1 when it waits, so a demo or a check can tell the two apart.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
SERVER = HERE / "server.py"
ROBOT = "layout-robot-1"
UNIT = "3B"
ACTIVITY = "framing"
TASK = "T-031"  # Frame partitions 3B: the robot's own task, asked by id so the answer cannot be a guess


def api_url(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    configured = (os.environ.get("AURORA_API_URL") or "").strip()
    if configured:
        return configured
    return f"http://127.0.0.1:{os.environ.get('PORT_BASE') or '8000'}"


def server_parameters(url: str | None = None) -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env={"AURORA_API_URL": api_url(url)})


def payload(result) -> dict:
    """The tool's answer as a dict, whether the SDK sends it as structured data or as JSON text."""
    data = getattr(result, "structured_content", None)
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if not isinstance(data, dict) or not data:
        texts = [part.text for part in getattr(result, "content", None) or [] if getattr(part, "text", None)]
        try:
            data = json.loads(texts[0]) if texts else {}
        except ValueError:
            data = {}
    return data if isinstance(data, dict) else {}


async def ask(url: str | None = None, asked_by: str = ROBOT, unit: str | None = UNIT,
              activity: str | None = ACTIVITY, task_id: str | None = TASK) -> dict:
    """One question to the MCP server, over stdio, exactly as an outside agent would ask it."""
    async with Client(server_parameters(url)) as client:
        result = await client.call_tool("can_start", {"asked_by": asked_by, "task_id": task_id, "unit": unit,
                                                      "activity": activity})
    return payload(result)


def decide(check: dict) -> tuple[bool, str]:
    """Start only on a yes; anything else, including unknown, is a wait."""
    summary = (check.get("summary") or "").strip()
    if check.get("allowed") == "yes":
        return True, f"robot: START framing in {check.get('unit') or UNIT}. {summary}"
    reasons = "; ".join(
        f"{reason.get('kind')} ({', '.join(reason.get('sources') or []) or 'no source'})"
        for reason in check.get("reasons") or []
    )
    verdict = check.get("allowed") or "nothing"
    return False, (f"robot: WAIT, Aurora answered {verdict} for {check.get('unit') or UNIT}. {summary} "
                   f"Reasons: {reasons or 'none given'}. The robot holds.")


async def main(argv: list[str]) -> int:
    url = argv[argv.index("--api") + 1] if "--api" in argv else None
    check = await ask(url)
    started, line = decide(check)
    print(line, flush=True)
    return 0 if started else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
