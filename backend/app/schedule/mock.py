"""Mock: canned plan and one canned proposal per flag."""
from app.core import models as m
from app.core import scenario
from app.core.store import store


def baseline() -> m.Plan:
    return m.Plan.model_validate(scenario.load()["plan"])


def propose(flag: m.Flag) -> m.Proposal | None:
    raw = scenario.load()["proposals"].get(flag.id)
    return m.Proposal.model_validate(raw) if raw else None


def apply(proposal: m.Proposal) -> m.Plan:
    plan = m.Plan.model_validate(store().get("plan", "current"))
    by_id = {shift.task_id: shift for shift in proposal.shifts}
    for task in plan.tasks:
        if task.id in by_id:
            task.start, task.end = by_id[task.id].new_start, by_id[task.id].new_end
    if proposal.handover_new is not None:
        plan.handover = proposal.handover_new
    return plan
