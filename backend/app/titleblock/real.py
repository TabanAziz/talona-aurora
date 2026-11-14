"""Read the sheet number and revision from a photo of a sheet's identification block, and answer the sender.

The answer has three values and only three: the sheet is current, it is superseded (then the current revision
and what changed), or the photo could not be read. Every rule here exists to make a wrong answer impossible and
an unreadable photo cheap: only a title block that is in the register, with a revision that exists for that
sheet and a read the model is sure about, becomes a "current" or "superseded" answer. Everything else answers
"could not read" and says nothing about which check failed.

A photo is information for the sender, never evidence of work: this area raises no flag, opens no waiting item,
calls no other area and makes exactly one model call (plus one repair).
"""
import io
import logging
import re
from pathlib import PurePosixPath

from PIL import Image, ImageOps

from app.core import config, llm
from app.core import models as m
from app.core.store import store
from app.live import delivery

log = logging.getLogger(__name__)

USER = "Read the identification block in this photo."
SYSTEM = """You read the identification block of a construction drawing sheet from a photograph. Report only what is printed in the image.

The identification block is the block that names the sheet: project name, sheet number and revision mark. On a drawn sheet it is usually the header band or the block in the lower right corner.

- sheet: the sheet number exactly as printed, for example A-201.
- revision: the revision mark exactly as printed, for example B or C.
- confidence: how sure you are that sheet and revision are both read correctly, from 0 to 1. Use a value below 0.9 when any character is partly covered, cut off, out of focus or lit badly, when the photo shows more than one sheet or more than one identification block, and whenever you would be completing a partly visible number or letter from what it probably is.
- read_text: the characters you read for the sheet number and the revision, on one line, exactly as printed.
- is_title_block: true only when the image shows a drawing sheet identification block with a sheet number and a revision mark in it. False for any other subject, including a plan without its identification block.

Never complete a partly visible number or letter. A missing digit is a missing digit. An empty string is the honest answer when a field is not printed or not visible."""
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sheet": {"type": "string"},
        "revision": {"type": "string"},
        "confidence": {"type": "number"},
        "read_text": {"type": "string"},
        "is_title_block": {"type": "boolean"},
    },
    "required": ["sheet", "revision", "confidence", "read_text", "is_title_block"],
}

CONFIDENCE_THRESHOLD = 0.90
MAX_BYTES = 8 * 1024 * 1024
MAX_EDGE = 1600
JPEG_QUALITY = 85
# Tried in this order; a model that refuses image input or is not offered passes the photo to the next one.
VISION_MODELS = ("mistral-small-2603", "mistral-large-2512", "mistral-medium-3-5")
ACCEPTED_MEDIA = {"image/jpeg", "image/png", "image/webp"}
MEDIA_ROOTS = (("/media/files/", lambda: config.data_dir() / "files"),
               ("/media/mock/", lambda: config.ROOT / "mocks" / "assets"))
REGISTER = config.ROOT / "data" / "drawings"

CURRENT_TEXT = ("Photo read: {sheet}, Rev {revision}. That is the current revision of the sheet. "
                "Work from it is fine.")
SUPERSEDED_TEXT = ("Photo read: {sheet}, Rev {revision}. That revision is superseded. {sheet} is at Rev "
                   "{current} now. {change}Reply here to confirm you have Rev {current} before you start.")
COULD_NOT_READ = ("I could not read the sheet number and revision from that photo. Send them as text, for "
                  "example A-201 Rev C, and I will answer again.")
REASON = {
    "below_threshold": "below_threshold",
    "not_a_title_block": "not_a_title_block",
    "unknown_sheet": "unknown_sheet",
    "unknown_revision": "unknown_revision",
    "model_unavailable": "model_unavailable",
    "unreadable_file": "unreadable_file",
    "no_sheet_in_photo": "no_sheet_in_photo",
}

SHEET_SHAPE = re.compile(r"^([A-Z]{1,2})-?(\d{3})$")
REVISION_SHAPE = re.compile(r"^\s*(?:rev(?:ision)?\.?\s*[-_ ]?)?\s*([A-Z])\s*[.)]?\s*$", re.IGNORECASE)
REVISION_FOLDER = re.compile(r"^[A-Z]$")


class ReadUnavailable(Exception):
    """No vision model answered the photo. The caller answers could not read."""


def _first_image(event: m.InboundEvent) -> m.Attachment | None:
    return next((item for item in event.attachments if item.kind == "image"), None)


def _path(url: str | None) -> str | None:
    """The file an attachment URL points at, or None when it is outside the media roots or missing."""
    if not url:
        return None
    if config.project_directory.get() is not None and url.startswith("/media/mock/"):
        return None
    for prefix, root in MEDIA_ROOTS:
        if url.startswith(prefix):
            base = root().resolve()
            path = (base / url[len(prefix):]).resolve()
            if base in path.parents and path.is_file():
                return path
    return None


def _jpeg(attachment: m.Attachment) -> bytes:
    """The photo as a JPEG of at most 1600 px on the long edge, or ReadUnavailable with the reason logged."""
    if (attachment.media_type or "").lower() not in ACCEPTED_MEDIA:
        raise ReadUnavailable(REASON["unreadable_file"])
    path = _path(attachment.url)
    if path is None:
        raise ReadUnavailable(REASON["unreadable_file"])
    try:
        data = path.read_bytes()
        if len(data) > MAX_BYTES:
            raise ReadUnavailable(REASON["unreadable_file"])
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        image.thumbnail((MAX_EDGE, MAX_EDGE))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=JPEG_QUALITY)
    except ReadUnavailable:
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ReadUnavailable(REASON["unreadable_file"]) from None
    return out.getvalue()


def _problems(answer: object) -> list[str]:
    if not isinstance(answer, dict):
        return ["the answer is not an object"]
    problems = [f"{key} is missing" for key in SCHEMA["required"] if key not in answer]
    if problems:
        return problems
    if not isinstance(answer["sheet"], str):
        problems.append("sheet is not a string")
    if not isinstance(answer["revision"], str):
        problems.append("revision is not a string")
    if not isinstance(answer["read_text"], str):
        problems.append("read_text is not a string")
    if not isinstance(answer["is_title_block"], bool):
        problems.append("is_title_block is not a boolean")
    confidence = answer["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        problems.append("confidence is not a number between 0 and 1")
    return problems


def _repair(user: str, answer: object, problems: list[str]) -> str:
    return (f"{user}\n\nYour previous answer did not match the schema: {'; '.join(problems)}. "
            "Answer again with only the JSON object.")


def _ask(jpeg: bytes, model: str) -> dict:
    answer = llm.complete_json(system=SYSTEM, user=USER, schema=SCHEMA, image=jpeg, model=model)
    problems = _problems(answer)
    if not problems:
        return answer
    repaired = llm.complete_json(system=SYSTEM, user=_repair(USER, answer, problems), schema=SCHEMA, image=jpeg,
                                 model=model)
    problems = _problems(repaired)
    if problems:
        raise llm.LLMError("the read did not match the schema after one repair",
                           category=llm.FailureCategory.INVALID_JSON)
    return repaired


def _refused_image_input(error: llm.LLMError) -> bool:
    text = str(error)
    return error.category == llm.FailureCategory.HTTP_STATUS and ("HTTP 400" in text or "HTTP 404" in text)


def read_photo(jpeg: bytes) -> tuple[dict, str]:
    """The model's read and the model id that gave it; the next vision model when one refuses image input."""
    last: llm.LLMError | None = None
    for model in VISION_MODELS:
        try:
            return _ask(jpeg, model), model
        except llm.LLMError as error:
            last = error
            if not _refused_image_input(error):
                break
            log.warning("titleblock: %s does not take the image, trying the next vision model", model)
    raise ReadUnavailable(REASON["model_unavailable"]) from last


def normalise_sheet(text: object) -> str | None:
    """`A201`, `A 201`, `a-201` and `A-201` all become `A-201`; anything else gives None."""
    value = re.sub(r"[\s_.]", "", str(text or "")).upper()
    match = SHEET_SHAPE.match(value)
    return f"{match[1]}-{match[2]}" if match else None


def normalise_revision(text: object) -> str | None:
    """`Rev B`, `rev.b`, `REV-B` and `b` all become `B`; anything else gives None."""
    match = REVISION_SHAPE.match(str(text or ""))
    return match[1].upper() if match else None


def register() -> dict[str, list[str]]:
    """Every sheet of the drawing register with its revision marks, lowest first. Data, not another area."""
    found: dict[str, list[str]] = {}
    root = config.drawings_dir(REGISTER)
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        marks = sorted((item.name.upper() for item in folder.iterdir()
                        if item.is_dir() and REVISION_FOLDER.match(item.name) and (item / "geometry.json").is_file()))
        if marks:
            found[folder.name.upper()] = marks
    return found


def current_revision(sheet: str) -> str | None:
    marks = register().get(sheet.upper()) or []
    return marks[-1] if marks else None


def _mentions(read_text: str, sheet: str, revision: str) -> bool:
    """The read text names the sheet and the revision in a revision context, not just somewhere in the text.

    A bare letter is not enough: "A-201 REV C" said to be Rev A must be refused, and so must a sheet number
    whose prefix letter happens to be a valid revision mark.
    """
    flat = re.sub(r"[\s\-_.]", "", (read_text or "").upper())
    if sheet.replace("-", "").upper() not in flat:
        return False
    marked = re.compile(rf"(?:rev(?:ision)?\.?\s*[-_ ]?|{re.escape(sheet)}\s*[/._-]?\s*)([A-Z])(?!\w)",
                        re.IGNORECASE)
    return any(match.group(1).upper() == revision.upper() for match in marked.finditer(read_text or ""))


def acceptance(answer: dict, register_: dict[str, list[str]]) -> tuple[str | None, str | None, str | None]:
    """The accepted (sheet, revision) or the refusal reason. The four conditions of the spec, in their order."""
    if not answer.get("is_title_block"):
        return None, None, REASON["not_a_title_block"]
    sheet = normalise_sheet(answer.get("sheet"))
    if sheet is None:
        return None, None, REASON["no_sheet_in_photo"]
    if sheet not in register_:
        return sheet, None, REASON["unknown_sheet"]
    revision = normalise_revision(answer.get("revision"))
    if revision is None or revision not in register_[sheet]:
        return sheet, revision, REASON["unknown_revision"]
    confidence = float(answer.get("confidence") or 0)
    if confidence < CONFIDENCE_THRESHOLD or not _mentions(str(answer.get("read_text") or ""), sheet, revision):
        return sheet, revision, REASON["below_threshold"]
    return sheet, revision, None


def _fact(event: m.InboundEvent, data: dict, confidence: float) -> m.Fact:
    read = data.get("status") == "read"
    subject = (f"Title block photo, {data.get('sheet')} Rev {data.get('revision')}" if read
               else "Title block photo, not read")
    return m.Fact(id=f"f-titleblock-{event.id}", event_id=event.id, type="other", subject=subject,
                  data=data, confidence=confidence if read else 0.0, quote=None)


def _change(sheet: str, revision: str, current: str) -> tuple[str, str | None]:
    """The stored sentence about this change and the overlay the answer carries, or empty and None."""
    diff = next((item for item in store().list("diffs")
                 if item.get("sheet") == sheet and item.get("from_rev") == revision
                 and item.get("to_rev") == current), None)
    if diff is None:
        return "", None
    return (diff.get("summary") or ""), _media(diff)


def _media(diff: dict) -> str | None:
    """The marked crop when the drawing renderer wrote one, else the overlay: the rule the outbox area uses."""
    overlay = (diff.get("overlay_url") or "").strip()
    if not overlay:
        return None
    if overlay.startswith("/media/files/"):
        for name in ("crop.png", "crop.svg"):
            url = str(PurePosixPath(overlay).with_name(name))
            base = (config.data_dir() / "files").resolve()
            target = (base / url.removeprefix("/media/files/")).resolve()
            if base in target.parents and target.is_file():
                return url
    return overlay


def inspect(event: m.InboundEvent) -> list[m.Fact]:
    """One fact about the photo: a read, or the reason it was refused. No image attachment, no fact."""
    attachment = _first_image(event)
    if attachment is None:
        return []
    data: dict = {"status": "not_read", "sheet": None, "revision": None, "confidence": 0.0, "read_text": "",
                  "reason": None, "change": ""}
    try:
        jpeg = _jpeg(attachment)
        answer, model = read_photo(jpeg)
    except ReadUnavailable as error:
        data["reason"] = str(error)
        log.warning("titleblock: %s not read: %s", event.id, data["reason"])
        return [_fact(event, data, 0.0)]
    data["read_text"] = str(answer.get("read_text") or "")
    data["model"] = model
    sheet, revision, reason = acceptance(answer, register())
    if reason is not None:
        data.update(sheet=sheet, revision=revision, confidence=float(answer.get("confidence") or 0),
                    reason=reason)
        log.info("titleblock: %s not accepted: %s", event.id, reason)
        return [_fact(event, data, data["confidence"])]
    current = current_revision(sheet)
    change, _ = _change(sheet, revision, current) if current and current != revision else ("", None)
    data.update(status="read", sheet=sheet, revision=revision, confidence=float(answer.get("confidence") or 0),
                reason=None, current=current, change=change)
    return [_fact(event, data, data["confidence"])]


def _text(fact: m.Fact) -> str:
    data = fact.data
    if data.get("status") != "read":
        return COULD_NOT_READ
    sheet, revision = data.get("sheet"), data.get("revision")
    current = data.get("current") or current_revision(sheet)
    if not current or current == revision:
        return CURRENT_TEXT.format(sheet=sheet, revision=revision)
    change = (data.get("change") or "").strip()
    return SUPERSEDED_TEXT.format(sheet=sheet, revision=revision, current=current,
                                 change=f"{change} " if change else "")


def _media_url(fact: m.Fact) -> str | None:
    data = fact.data
    if data.get("status") != "read" or not data.get("current") or data.get("current") == data.get("revision"):
        return None
    current = data["current"]
    diff = next((item for item in store().list("diffs")
                 if item.get("sheet") == data["sheet"] and item.get("from_rev") == data["revision"]
                 and item.get("to_rev") == current), None)
    return _media(diff) if diff else None


def react(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    """One answer to the sender, in the same thread and on the same channel. Nothing when there was no photo."""
    fact = next((item for item in facts if item.id == f"f-titleblock-{event.id}"), None)
    if fact is None:
        return []
    message = m.OutboundMessage(
        id=f"o-titleblock-{event.id}", channel=event.channel, to=event.sender, text=_text(fact),
        media_url=_media_url(fact), reason="Title block photo read", in_reply_to=event.id,
        created_at=event.received_at,
    )
    return [delivery.deliver(message)]
