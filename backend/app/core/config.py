"""Settings from the environment. Nothing here has a secret default."""
import functools
import os
import re
import subprocess
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERSION = "0.1.0"
# The hosted image is built from a copy of the tracked files without .git, so the deploy writes the commit here.
BUILD_COMMIT_FILE = ROOT / "backend" / "BUILD_COMMIT"
COMMIT = re.compile(r"[0-9a-f]{7,40}")

AREAS = [
    "replay",
    "voice",
    "titleblock",
    "extract",
    "record",
    "rules_drawings",
    "rules_sequence",
    "rules_resources",
    "drawings",
    "crosscheck",
    "schedule",
    "decisions",
    "outbox",
    "qa",
    "gate",
    "readiness",
    "insights",
    "autonomy",
    "command",
    "learning",
    "followup",
    "names",
    "machine",
    "machinereport",
    "telegram",
    "email",
    "whatsapp",
]
EXTERNAL = ["llm", "voice_api", "telegram_api", "email_api", "whatsapp_api"]


def load_dotenv() -> None:
    """Fill missing variables from the repository's .env file."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@functools.cache
def build_commit() -> str | None:
    """The commit this app was built from: the deploy's BUILD_COMMIT file, else the checkout's HEAD, else unknown."""
    try:
        stamped = BUILD_COMMIT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        stamped = ""
    if COMMIT.fullmatch(stamped):
        return stamped
    # git walks up from a folder, so a root that only sits inside another checkout would report that one's commit.
    if not (ROOT / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    head = out.stdout.strip()
    return head if out.returncode == 0 and COMMIT.fullmatch(head) else None


def build_version() -> str:
    """VERSION with the first 12 characters of the build commit, so /health tells two builds apart."""
    commit = build_commit()
    return f"{VERSION}+{commit[:12]}" if commit else VERSION


def port() -> int:
    return int(os.environ.get("PORT") or os.environ.get("PORT_BASE") or 8000)


project_directory: ContextVar[Path | None] = ContextVar("aurora_project_directory", default=None)
project_id: ContextVar[str | None] = ContextVar("aurora_project_id", default=None)


def base_data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or ROOT / ".local")


def data_dir() -> Path:
    path = project_directory.get() or base_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def drawings_dir(default: Path | None = None) -> Path:
    return data_dir() / "files" / "drawings" if project_directory.get() is not None else (default or ROOT / "data" / "drawings")


def project_metadata_file(default: Path | None = None) -> Path:
    return data_dir() / "project.json" if project_directory.get() is not None else (default or ROOT / "data" / "project" / "project.json")


def flag(name: str) -> bool | None:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return None
    return value in ("1", "true", "yes", "on")


def mock_forced(area: str) -> bool | None:
    """USE_MOCK_<AREA>: true forces the mock, false forces the real module, unset picks real when it exists."""
    return flag(f"USE_MOCK_{area.upper()}")


def external_is_mock(service: str) -> bool:
    """External services stay mocked unless USE_MOCK_<SERVICE>=false, so no test run touches a live account."""
    return flag(f"USE_MOCK_{service.upper()}") is not False
