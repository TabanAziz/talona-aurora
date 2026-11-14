"""Applies a superintendent's decision on a flag: flag status, plan change, notices to the affected crews."""
import re
from datetime import datetime

from app.core import models as m
from app.core import pipeline, site
from app.core.registry import area
from app.core.store import store
from app.live import delivery

# The crews coordinate in the site group chat, so notices go there unless a crew is known elsewhere.
CREW_CHANNEL: m.Channel = "telegram"

ALLOWED_FROM: dict[str, set[str]] = {
    "hold_work": {"open", "released"},
    "release_work": {"held"},
    "reschedule": {"open"},
    "dismiss": {"open"},
}


Refused = pipeline.DecisionRefused


def decide(request: m.DecisionRequest) -> m.Decision:
    s = store()
    raw = s.get("flags", request.flag_id)
    if raw is None:
        raise KeyError(request.flag_id)
    flag = m.Flag.model_validate(raw)
    decided_by = request.decided_by.strip()
    if not decided_by:
        raise Refused("a decision needs the name of who decided")
    if request.action not in ALLOWED_FROM:
        raise Refused(f"{request.action} runs without a decision; only hold, release, reschedule and dismiss are decided")
    if flag.status not in ALLOWED_FROM[request.action]:
        raise Refused(f"flag {flag.id} is {flag.status}; {request.action} needs it to be "
                      + " or ".join(sorted(ALLOWED_FROM[request.action])))
    proposal = _proposal(request, flag)

    now = pipeline.now()
    decision = m.Decision(
        id=_decision_id(flag.id, request.action), flag_id=flag.id, action=request.action,
        proposal_id=proposal.id if proposal else None,
        reason=(request.reason or "").strip() or (proposal.summary if proposal and request.action != "dismiss" else None),
        decided_by=decided_by, decided_at=now, standing_rule=request.standing_rule,
        authorization_id=request.authorization_id,
    )
    if request.action == "hold_work":
        notices = _hold(flag, proposal, decision)
    elif request.action == "release_work":
        notices = _release(flag, decision)
    elif request.action == "reschedule":
        notices = _reschedule(flag, proposal, decision)
    else:
        notices = []
        _set_flag_status(flag, "dismissed")
        if proposal is not None:
            _set_proposal_status(proposal, "rejected")
    for message in notices:
        _deliver(message, decision)
    return decision


def _proposal(request: m.DecisionRequest, flag: m.Flag) -> m.Proposal | None:
    """The proposal the decision acts on. A named proposal must belong to the flag and propose this action."""
    s = store()
    if request.proposal_id:
        raw = s.get("proposals", request.proposal_id)
        if raw is None:
            raise Refused(f"proposal {request.proposal_id} does not exist")
        proposal = m.Proposal.model_validate(raw)
        if proposal.flag_id not in (None, flag.id):
            raise Refused(f"proposal {proposal.id} belongs to flag {proposal.flag_id}, not {flag.id}")
        if request.action != "dismiss" and proposal.action != request.action:
            raise Refused(f"proposal {proposal.id} proposes {proposal.action}, not {request.action}")
        rehold = proposal.status == "accepted" and request.action == "hold_work" and flag.status == "released"
        if proposal.status != "proposed" and not rehold:
            raise Refused(f"proposal {proposal.id} is already {proposal.status}")
    else:
        raw = s.get("proposals", flag.proposal_id) if flag.proposal_id else None
        if raw is None:
            raw = next((p for p in s.list("proposals") if p.get("flag_id") == flag.id and p.get("status") == "proposed"), None)
        proposal = m.Proposal.model_validate(raw) if raw else None
        if proposal is not None and request.action != "dismiss" and proposal.action != request.action:
            proposal = None
    if request.action == "reschedule" and (proposal is None or not proposal.shifts):
        raise Refused(f"flag {flag.id} has no calculated plan change to accept")
    return proposal


def _hold(flag: m.Flag, proposal: m.Proposal | None, decision: m.Decision) -> list[m.OutboundMessage]:
    plan = _plan()
    task = _held_task(flag, proposal, plan)
    if task is None:
        raise Refused(f"flag {flag.id} names no planned task that could be held")
    if task.status == "done":
        raise Refused(f"task {task.id} is already done and can not be held")
    task.status = "on_hold"
    store().put("plan", "current", plan)
    _set_flag_status(flag, "held")
    if proposal is not None:
        _set_proposal_status(proposal, "accepted")

    unit = flag.affected.get("unit") or task.unit
    where = f" on {unit}" if unit else ""
    text = f"Hold{where}. {task.name} stays on hold: {flag.summary} Do not start until the superintendent releases it."
    media_url, buttons = None, []
    if flag.type in ("stale_drawing", "unacknowledged_change"):
        diff = store().get("diffs", flag.diff_id) if flag.diff_id else None
        media_url = diff["overlay_url"] if diff else None
        sheet = flag.affected.get("sheet") or (diff["sheet"] if diff else None)
        revision = flag.affected.get("revision") or (diff["to_rev"] if diff else None)
        if sheet and revision:
            text = (f"Hold{where}. {flag.summary} Do not start {_lower_first(task.name)} until you confirm "
                    f"{sheet} Rev {revision}.")
            buttons = ["Confirmed"]
    return [_notice(decision, flag.affected.get("crew") or task.crew, text, f"{decision.decided_by} held work{where}",
                    media_url=media_url, buttons=buttons)]


def _release(flag: m.Flag, decision: m.Decision) -> list[m.OutboundMessage]:
    """Releases the work this flag held, found through the decision that held it."""
    s = store()
    plan = _plan()
    holds = [d for d in s.list("decisions") if d["flag_id"] == flag.id and d["action"] == "hold_work"]
    still_held = {task.id for other in s.list("flags") if other["id"] != flag.id and other["status"] == "held"
                  for task in _tasks_held_by(m.Flag.model_validate(other), plan)}
    released = [t for t in _tasks_held_by(flag, plan) if t.status == "on_hold" and t.id not in still_held]
    for task in released:
        task.status = "planned"
    s.put("plan", "current", plan)
    _set_flag_status(flag, "released")

    by_crew: dict[str, list[str]] = {}
    for task in released:
        by_crew.setdefault(task.crew, []).append(f"Released: you may start {_lower_first(task.name)} as planned.")
    unit = flag.affected.get("unit")
    where = f" in {unit}" if unit else ""
    return [_notice(decision, crew, " ".join(lines), f"{decision.decided_by} released work{where}")
            for crew, lines in by_crew.items()]


def _tasks_held_by(flag: m.Flag, plan: m.Plan) -> list[m.Task]:
    """The tasks this flag's hold decisions put on hold, found the same way the hold found them."""
    s = store()
    holds = [d for d in s.list("decisions") if d["flag_id"] == flag.id and d["action"] == "hold_work"]
    proposals = [s.get("proposals", d["proposal_id"]) if d.get("proposal_id") else None for d in holds] or [None]
    tasks: list[m.Task] = []
    for raw in proposals:
        task = _held_task(flag, m.Proposal.model_validate(raw) if raw else None, plan)
        if task is not None and task not in tasks:
            tasks.append(task)
    return tasks


def _held_task(flag: m.Flag, proposal: m.Proposal | None, plan: m.Plan) -> m.Task | None:
    """The planned task a hold applies to: named by the proposal or the flag, else the crew's task in the unit."""
    for task_id in ((proposal.params.get("task") if proposal else None), flag.affected.get("task")):
        task = next((t for t in plan.tasks if task_id and t.id == task_id), None)
        if task is not None:
            return task
    crew, unit = flag.affected.get("crew"), flag.affected.get("unit")
    candidates = [t for t in plan.tasks if crew and unit and t.crew == crew and t.unit == unit and t.status != "done"]
    if flag.work_starts_at is not None:
        candidates.sort(key=lambda t: abs((t.start - flag.work_starts_at).total_seconds()))
    return candidates[0] if candidates else None


def _reschedule(flag: m.Flag, proposal: m.Proposal, decision: m.Decision) -> list[m.OutboundMessage]:
    # A proposal is calculated once when the flag is raised; a later message can change the numbers behind it.
    # The superintendent must see the plan change that will run, so a recalculated one is stored and refused.
    fresh = area("schedule").propose(flag) if proposal.basis == "calculated" else None
    if fresh is not None and fresh.action == "reschedule" and _effect(fresh) != _effect(proposal):
        base, version = fresh.id, 2
        while store().get("proposals", fresh.id) is not None:
            fresh.id = f"{base}-{version}"
            version += 1
        store().put("proposals", fresh.id, fresh)
        _set_proposal_status(proposal, "rejected")
        store().put("flags", flag.id, flag.model_copy(update={"proposal_id": fresh.id}))
        raise Refused(f"the plan change for flag {flag.id} was recalculated from newer messages; review it again")
    try:
        plan: m.Plan = area("schedule").apply(proposal)
    except ValueError as error:
        raise Refused(str(error)) from error
    store().put("plan", "current", plan)
    _set_proposal_status(proposal, "accepted")
    _set_flag_status(flag, "resolved")

    by_crew: dict[str, list[str]] = {}
    for shift in proposal.shifts:
        by_crew.setdefault(shift.crew, []).append(_describe(shift))
    return [_notice(decision, crew, " ".join(lines), f"{decision.decided_by} accepted the changed plan")
            for crew, lines in by_crew.items()]


def _effect(proposal: m.Proposal) -> tuple:
    return (proposal.handover_new, sorted((s.task_id, s.new_start, s.new_end) for s in proposal.shifts))


def _describe(shift: m.TaskShift) -> str:
    # Crews read site time, so a shift that crosses site midnight is a move to another day.
    if site.local(shift.new_start).date() != site.local(shift.old_start).date():
        return f"{shift.name} moves from {_day(shift.old_start)} to {_day(shift.new_start)}."
    return (f"{shift.name} now runs {_clock(shift.new_start)} to {_clock(shift.new_end)} on {_day(shift.new_start)}, "
            f"was {_clock(shift.old_start)} to {_clock(shift.old_end)}.")


def _day(at: datetime) -> str:
    local = site.local(at)
    return f"{local:%A %b} {local.day}"


def _clock(at: datetime) -> str:
    return f"{site.local(at):%H:%M}"


def _notice(decision: m.Decision, crew: str, text: str, reason: str, *, media_url: str | None = None,
            buttons: list[str] | None = None) -> m.OutboundMessage:
    return m.OutboundMessage(
        id=f"o-{decision.id}-{_slug(crew)}", channel=CREW_CHANNEL, to=crew, text=text, media_url=media_url,
        buttons=buttons or [], reason=reason, created_at=decision.decided_at,
    )


def _deliver(message: m.OutboundMessage, decision: m.Decision) -> None:
    """Sends through the one delivery path, which stores the outcome and never raises, so a failed send never
    undoes the decision; the notice then shows as failed."""
    sent = delivery.deliver(message)
    if sent.status in ("sent", "simulated"):
        title = f"Sent to {sent.to}"
    elif sent.status == "failed":
        title = f"Not delivered to {sent.to}"
    else:
        title = f"Queued for {sent.to}"
    store().put("record", f"r-out-{sent.id}", m.RecordEntry(
        id=f"r-out-{sent.id}", at=sent.created_at, kind="notice", title=title,
        detail=sent.text, actor="Aurora", refs={"message": sent.id, "flag": decision.flag_id, "decision": decision.id},
    ))


def _plan() -> m.Plan:
    return m.Plan.model_validate(store().get("plan", "current"))


def _set_flag_status(flag: m.Flag, status: m.FlagStatus) -> None:
    store().put("flags", flag.id, flag.model_copy(update={"status": status}))


def _set_proposal_status(proposal: m.Proposal, status: str) -> None:
    store().put("proposals", proposal.id, proposal.model_copy(update={"status": status}))


def _decision_id(flag_id: str, action: str) -> str:
    """Stable for the first decision of a kind, so the record and the UI can link to it; later ones get a number."""
    base = f"d-{flag_id}-{action}"
    taken = {d["id"] for d in store().list("decisions")}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _lower_first(text: str) -> str:
    """Keeps unit ids like 3B intact inside a sentence."""
    return text[:1].lower() + text[1:]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
