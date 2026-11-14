"""Who is who on the project, and where each person and crew is reached on the live channels.

People and crews come from the project (the store, else the record area) and from data/project/project.json
(foremen and contacts). Real Telegram ids, usernames, mail addresses and WhatsApp numbers never live in git:
they come from the untracked file DATA_DIR/directory.json and from the variable LIVE_DIRECTORY, both in the
format described in backend/app/live/README.md. The Telegram group chat is TELEGRAM_CHAT_ID, the same variable
the Telegram channel sends to, so the two can never disagree.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field, replace
from email.utils import parseaddr
from typing import Literal

from app.core import config
from app.core.registry import area
from app.core.store import store

log = logging.getLogger(__name__)

PROJECT_FILE = config.ROOT / "data" / "project" / "project.json"
MAPPING_FILE_NAME = "directory.json"
MAPPING_ENV = "LIVE_DIRECTORY"
GROUP_ENV = "TELEGRAM_CHAT_ID"
CHANNELS = ("telegram", "email", "whatsapp")
GROUP_NAME = "Site group chat"

Kind = Literal["person", "crew", "group", "unknown"]


@dataclass(frozen=True)
class Contact:
    """A person, a crew, the group chat, or an unknown sender. Handles stay out of repr so a log line cannot leak them."""

    name: str
    kind: Kind
    role: str | None = None
    crew: str | None = None
    handle: str | None = field(default=None, repr=False)
    telegram: tuple[str, ...] = field(default=(), repr=False)
    email: tuple[str, ...] = field(default=(), repr=False)
    whatsapp: tuple[str, ...] = field(default=(), repr=False)
    language: str | None = None

    @property
    def known(self) -> bool:
        return self.kind != "unknown"


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _telegram(value: str) -> str | None:
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        return text
    username = text.removeprefix("@").lower()
    return f"@{username}" if re.fullmatch(r"[a-z0-9_]{3,64}", username) else None


def _email(value: str) -> str | None:
    address = parseaddr(value.strip())[1].strip().lower()
    return address if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address) else None


def _whatsapp(value: str) -> str | None:
    digits = re.sub(r"[\s()-]", "", value.strip().removeprefix("whatsapp:"))
    return digits if re.fullmatch(r"\+\d{6,15}", digits) else None


NORMALIZE = {"telegram": _telegram, "email": _email, "whatsapp": _whatsapp}


def _language(value: object) -> str | None:
    """An ISO 639-1 code from "pl", "PL" or "pl-PL"."""
    if not isinstance(value, str):
        return None
    code = value.strip().lower().replace("_", "-").split("-")[0]
    return code if re.fullmatch(r"[a-z]{2}", code) else None


def _stem(crew: str) -> str:
    return re.sub(r"\s+crew$", "", crew.strip(), flags=re.IGNORECASE)


def _project_crews() -> list[str]:
    try:
        current = store().get("project", "current")
        crews = current["crews"] if current else area("record").project().crews
    except Exception as error:
        log.warning("directory: project crews unavailable: %s", type(error).__name__)
        return []
    return [crew for crew in crews if isinstance(crew, str) and crew.strip()]


def _project_people(crews: list[str]) -> list[Contact]:
    path = config.project_metadata_file(PROJECT_FILE)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        log.warning("directory: %s unreadable: %s", PROJECT_FILE.name, type(error).__name__)
        return []
    known_crews = {_key(crew): crew for crew in crews}
    people: list[Contact] = []
    for item in data.get("crews") or []:
        foreman, crew = item.get("foreman"), known_crews.get(_key(item.get("name") or ""))
        if isinstance(foreman, str) and foreman.strip() and crew:
            people.append(Contact(name=foreman.strip(), kind="person", role=f"{_stem(crew)} foreman", crew=crew))
    for item in data.get("contacts") or []:
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            people.append(Contact(name=name.strip(), kind="person", role=item.get("role") or None))
    return people


def _parse_mapping(text: str, source: str) -> dict[str, dict[str, list[str]]]:
    try:
        raw = json.loads(text)
    except ValueError:
        log.warning("directory: %s is not valid JSON, ignored", source)
        return {}
    if not isinstance(raw, dict):
        log.warning("directory: %s must be a JSON object, ignored", source)
        return {}
    mapping: dict[str, dict[str, list[str]]] = {}
    for name, handles in raw.items():
        if not isinstance(handles, dict):
            log.warning("directory: entry %r in %s must be an object, ignored", name, source)
            continue
        entry = mapping.setdefault(_key(str(name)), {})
        for channel in CHANNELS:
            values = handles.get(channel) or []
            for value in [values] if isinstance(values, (str, int)) else values:
                normalized = NORMALIZE[channel](str(value))
                if normalized is None:
                    log.warning("directory: a %s handle of %r in %s is malformed, ignored", channel, name, source)
                elif normalized not in entry.setdefault(channel, []):
                    entry[channel].append(normalized)
        if "language" in handles:
            language = _language(handles["language"])
            if language is None:
                log.warning("directory: the language of %r in %s is not a language code, ignored", name, source)
            else:
                entry["language"] = [language]
    return mapping


def mapping_file():
    return config.data_dir() / MAPPING_FILE_NAME


def _mapping() -> dict[str, dict[str, list[str]]]:
    """File first, then the variable; both add handles, neither removes any."""
    sources: list[tuple[str, str]] = []
    path = mapping_file()
    if path.is_file():
        try:
            sources.append((path.read_text(encoding="utf-8"), f"DATA_DIR/{MAPPING_FILE_NAME}"))
        except OSError as error:
            log.warning("directory: DATA_DIR/%s unreadable: %s", MAPPING_FILE_NAME, type(error).__name__)
    if config.project_directory.get() is None and os.environ.get(MAPPING_ENV, "").strip():
        sources.append((os.environ[MAPPING_ENV], MAPPING_ENV))
    merged: dict[str, dict[str, list[str]]] = {}
    for text, source in sources:
        for name, handles in _parse_mapping(text, source).items():
            entry = merged.setdefault(name, {})
            for channel, values in handles.items():
                entry.setdefault(channel, [])
                entry[channel].extend(v for v in values if v not in entry[channel])
    return merged


def everyone() -> list[Contact]:
    """Every person and crew of the project, with their mapped handles."""
    crews = _project_crews()
    base = _project_people(crews) + [Contact(name=crew, kind="crew", crew=crew) for crew in crews]
    mapping = _mapping()
    names = {_key(contact.name) for contact in base}
    for name in mapping:
        if name not in names:
            log.warning("directory: mapping names %r, who is not a person or crew of the project; ignored", name)
    contacts = []
    for contact in base:
        entry = mapping.get(_key(contact.name), {})
        handles = {channel: tuple(entry.get(channel, [])) for channel in CHANNELS}
        contacts.append(replace(contact, **handles, language=(entry.get("language") or [None])[0]))
    return contacts


def people() -> list[Contact]:
    return [contact for contact in everyone() if contact.kind == "person"]


def crews() -> list[Contact]:
    return [contact for contact in everyone() if contact.kind == "crew"]


def lookup(name: str) -> Contact | None:
    """A person or crew by name, ignoring case and spacing."""
    wanted = _key(name or "")
    return next((contact for contact in everyone() if _key(contact.name) == wanted), None)


def group_chat() -> str | None:
    from app.workspace.channels import binding, group_chat as bound_group
    if binding("telegram"):
        return bound_group()
    if config.project_directory.get() is not None:
        return None
    value = os.environ.get(GROUP_ENV, "").strip()
    return _telegram(value) if value else None


def resolve(channel: str, handle: str | int | None) -> Contact:
    """The person, crew or group chat behind a channel handle. Anyone not mapped stays unknown with the raw handle."""
    raw = "" if handle is None else str(handle)
    unknown = Contact(name=raw or "unknown", kind="unknown", handle=raw)
    normalize = NORMALIZE.get(channel)
    if normalize is None or not raw.strip():
        return unknown
    normalized = normalize(raw)
    if channel == "telegram" and normalized is None and re.fullmatch(r"[A-Za-z0-9_]{3,64}", raw.strip()):
        normalized = _telegram("@" + raw.strip())
    if normalized is None:
        return unknown
    if channel == "telegram" and normalized == group_chat():
        return Contact(name=GROUP_NAME, kind="group", role="All crews", handle=raw, telegram=(normalized,))
    for contact in everyone():
        if normalized in getattr(contact, channel):
            return replace(contact, handle=raw)
    return unknown


def language(name: str, channel: str | None = None) -> str | None:
    """The language a person or crew reads, as an ISO 639-1 code, or None when none is stored. `name` may also be a
    handle on `channel`. A crew without its own language is read by its foreman."""
    contact = lookup(name)
    if contact is None and channel:
        contact = resolve(channel, name)
    if contact is None or not contact.known:
        return None
    if contact.language or contact.kind != "crew":
        return contact.language
    return next((person.language for person in people() if person.crew == contact.crew and person.language
                 and person.role and person.role.endswith("foreman")), None)


def reach(name: str, channel: str) -> list[str]:
    """Where a person or crew is reached on a channel. A crew without its own handle is reached through its foreman;
    on Telegram anyone without a personal chat is reached in the group chat."""
    if channel not in CHANNELS:
        return []
    contact = lookup(name)
    handles: list[str] = list(getattr(contact, channel)) if contact else []
    if contact and contact.kind == "crew" and not handles:
        for person in people():
            if person.crew == contact.crew and person.role and person.role.endswith("foreman"):
                handles.extend(getattr(person, channel))
    if channel == "telegram" and not handles and contact is not None and group_chat():
        handles.append(group_chat())
    return handles
