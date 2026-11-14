"""Detect drawing conflicts from arrived revision, work and confirmation facts."""
import hashlib
import re
from datetime import datetime

from app.core import models as m
from app.core.store import store


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _key(fact: m.Fact) -> tuple[str, ...]:
    return tuple(_text(fact.data.get(name)) for name in ("unit", "crew", "task", "sheet"))


def _applies(revision: m.Fact, sheet: str, unit: str) -> bool:
    if sheet and revision.data["sheet"] != sheet:
        return False
    units = revision.data.get("units")
    if units is None:
        return bool(sheet)
    if not isinstance(units, list) or not all(isinstance(u, str) for u in units):
        return False
    return unit in units


def _evidence(fact: m.Fact, event: m.InboundEvent) -> m.Evidence:
    attachment = next((a.url for a in event.attachments if a.kind in ("pdf", "image") and a.url), None)
    return m.Evidence(event_id=event.id, channel=event.channel, sender=event.sender,
                      at=event.sent_at, quote=fact.quote or event.transcript or event.text,
                      attachment_url=attachment)


def _superseded(old: str, current: m.Fact, revisions: list[m.Fact]) -> bool:
    seen = set()
    predecessor = _text(current.data.get("replaces"))
    while predecessor and predecessor not in seen:
        if predecessor == old:
            return True
        seen.add(predecessor)
        earlier = next((f for f in reversed(revisions) if f.data.get("revision") == predecessor), None)
        predecessor = _text(earlier.data.get("replaces")) if earlier else ""
    return False


def _incident_id(work: m.Fact, revision: m.Fact, existing: list[m.Flag]) -> str:
    sheet = _text(revision.data.get("sheet"))
    unit = _text(work.data.get("unit"))
    task = _text(work.data.get("task"))
    crew = _text(work.data.get("crew"))
    version = _text(revision.data.get("revision"))
    start = _time(work.data.get("start"))
    for flag in existing:
        if (flag.type in ("stale_drawing", "unacknowledged_change")
                and flag.affected.get("sheet") == sheet and flag.affected.get("unit") == unit
                and flag.affected.get("task", "") == task and flag.affected.get("crew") == crew
                and flag.work_starts_at == start and flag.affected.get("revision") == version):
            return flag.id
    # Keep the readable unit id for its first incident; distinguish further tasks and revisions.
    slug = re.sub(r"[^a-z0-9]+", "-", unit.lower()).strip("-")
    base = f"f-stale-{slug or 'work'}"
    if not any(flag.id == base for flag in existing):
        return base
    identity = "|".join((sheet, unit, crew, task, str(start), version))
    return f"{base}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"


def evaluate(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.Flag]:
    """Evaluate announced work before its start using only already received sources."""
    if not any(f.type in ("drawing_revision", "work_planned", "work_started", "acknowledgement") for f in facts):
        return []
    s = store()
    events = {raw["id"]: m.InboundEvent.model_validate(raw) for raw in s.list("events")}
    events[event.id] = event
    arrived = {key: value for key, value in events.items() if value.received_at <= event.received_at}
    stored = {raw["id"]: m.Fact.model_validate(raw) for raw in s.list("facts")}
    stored.update({fact.id: fact for fact in facts if fact.event_id == event.id})
    known = [fact for fact in stored.values() if fact.event_id in arrived]
    known.sort(key=lambda f: (arrived[f.event_id].sent_at, arrived[f.event_id].received_at, f.id))
    revisions = [f for f in known if f.type == "drawing_revision"
                 and _text(f.data.get("sheet")) and _text(f.data.get("revision"))]
    acknowledgements = [f for f in known if f.type == "acknowledgement"]
    latest_work = {_key(f): f for f in known if f.type in ("work_planned", "work_started")}
    existing = [m.Flag.model_validate(raw) for raw in s.list("flags")]
    emitted = {}
    changed_sheets = {_text(f.data.get("sheet")) for f in facts if f.type == "drawing_revision"}
    confirmed = {(_text(f.data.get("sheet")), _text(f.data.get("crew")))
                 for f in facts if f.type == "acknowledgement"}
    for work in latest_work.values():
        if work.event_id != event.id and not changed_sheets and not confirmed:
            continue
        unit, crew, task, sheet = _key(work)
        start = _time(work.data.get("start"))
        if not unit or not crew or start is None:
            continue
        applicable = [f for f in revisions if _applies(f, sheet, unit)]
        replaced = {(f.data["sheet"], _text(f.data.get("replaces"))) for f in applicable}
        by_sheet = {f.data["sheet"]: f for f in applicable
                    if (f.data["sheet"], f.data["revision"]) not in replaced}
        for sheet_name, revision in by_sheet.items():
            candidates = [f for f in latest_work.values() if _key(f)[:3] == (unit, crew, task)
                          and _key(f)[3] in ("", sheet_name)]
            effective = max(candidates, key=lambda f: (arrived[f.event_id].sent_at,
                                                       arrived[f.event_id].received_at, f.id))
            if work.id != effective.id:
                continue
            if (work.event_id != event.id and sheet_name not in changed_sheets
                    and (sheet_name, crew) not in confirmed):
                continue
            current = revision.data["revision"]
            stated = _text(work.data.get("revision"))
            flag_id = _incident_id(work, revision, existing + list(emitted.values()))
            previous = next((f for f in existing if f.id == flag_id), None)
            same_sheet = [f for f in applicable if f.data["sheet"] == sheet_name]
            issued_at = min(arrived[f.event_id].sent_at for f in same_sheet if f.data["revision"] == current)
            stale = bool(stated) and _superseded(stated, revision, same_sheet)
            if stated and not stale and stated != current:
                continue
            ack = next((f for f in reversed(acknowledgements)
                        if f.data.get("sheet") == sheet_name and f.data.get("revision") == current
                        and f.data.get("crew") == crew
                        and arrived[f.event_id].sent_at >= issued_at), None)
            confirmation = (work if stated == current else ack if ack and
                            (not stale or arrived[ack.event_id].sent_at > arrived[work.event_id].sent_at) else None)
            if confirmation:
                covered = [f for f in existing if f.type in ("stale_drawing", "unacknowledged_change")
                           and f.affected.get("sheet") == sheet_name and f.affected.get("unit") == unit
                           and f.affected.get("crew") == crew and f.affected.get("task", "") == task
                           and f.work_starts_at == start and f.status == "open"
                           and (f.affected.get("revision") == current
                                or _superseded(f.affected.get("revision", ""), revision, same_sheet))]
                for incident in covered:
                    evidence = {e.event_id: e for e in incident.evidence}
                    evidence[confirmation.event_id] = _evidence(confirmation, arrived[confirmation.event_id])
                    emitted[incident.id] = incident.model_copy(update={
                        "status": "resolved", "evidence": list(evidence.values()),
                        "summary": f"{crew} confirmed {sheet_name} Rev {current}; the drawing conflict is resolved.",
                    })
                continue
            if start <= event.received_at or (confirmed and not changed_sheets and not previous):
                continue
            status = previous.status if previous else "open"
            if status == "resolved" and not any(d.get("flag_id") == flag_id for d in s.list("decisions")):
                status = "open"
            diff = next((d for d in reversed(s.list("diffs"))
                         if d["sheet"] == sheet_name and d["to_rev"] == current), None)
            summary = (f"{crew} announced work in {unit} using {sheet_name} Rev {stated}. "
                       f"Rev {current} supersedes it." if stale else
                       f"{crew} announced work in {unit} without confirming {sheet_name} Rev {current}.")
            flag = m.Flag(
                id=flag_id, type="stale_drawing" if stale else "unacknowledged_change", severity="high",
                title=f"{crew} plans to build {unit} {'from an outdated drawing' if stale else 'before confirming a change'}",
                summary=summary, raised_at=previous.raised_at if previous else event.received_at,
                work_starts_at=start, status=status,
                affected={"unit": unit, "crew": crew, "task": task, "sheet": sheet_name, "revision": current},
                evidence=[_evidence(revision, arrived[revision.event_id]), _evidence(work, arrived[work.event_id])],
                diff_id=diff["id"] if diff else (previous.diff_id if previous else None),
                proposal_id=previous.proposal_id if previous else None,
            )
            emitted[flag_id] = flag
    return list(emitted.values())
