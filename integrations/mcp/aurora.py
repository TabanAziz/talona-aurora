"""Read-only client for the Aurora HTTP API, standard library only.

The base URL comes from AURORA_API_URL, else from this machine's PORT_BASE, so the server works the same way
in a container as it does on a laptop. Every call has a timeout: a robot that hangs on a dead API is as
bad as a robot that starts without asking.
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_S = 5.0


class Unreachable(RuntimeError):
    """Aurora did not answer, or did not answer with JSON. The caller must treat the state as unknown."""


def timeout() -> float:
    try:
        return float(os.environ.get("AURORA_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError:
        return DEFAULT_TIMEOUT_S


def base_url() -> str:
    explicit = (os.environ.get("AURORA_API_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"http://127.0.0.1:{os.environ.get('PORT_BASE') or '8000'}"


def _request(method: str, path: str, body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base_url() + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout()) as response:
            return json.loads(response.read().decode() or "null")
    except urllib.error.HTTPError as error:
        raise Unreachable(f"Aurora answered HTTP {error.code} for {path}") from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise Unreachable(f"Aurora is unreachable at {base_url()}: {getattr(error, 'reason', error)}") from None


def get(path: str) -> object:
    return _request("GET", path)


def post(path: str, body: dict) -> object:
    return _request("POST", path, body)
