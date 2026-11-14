"""Mock: canned effects per flag and action."""
from app.core import models as m
from app.core import scenario
from app.core import pipeline
from app.core.registry import area
from app.core.store import store


def decide(request: m.DecisionRequest) -> m.Decision:
    s = store()
    effects = scenario.for_decision(request.flag_id, request.action)
    flag = s.get("flags", request.flag_id)
    s.put("flags", request.flag_id, {**flag, "status": effects.get("flag_status", flag["status"])})
    if request.proposal_id and (raw := s.get("proposals", request.proposal_id)):
        proposal = m.Proposal.model_validate({**raw, "status": "accepted"})
        s.put("proposals", proposal.id, proposal)
        if proposal.action == "reschedule":
            s.put("plan", "current", area("schedule").apply(proposal))
    plan = s.get("plan", "current")
    for task in plan["tasks"]:
        if task["id"] in effects.get("task_status", {}):
            task["status"] = effects["task_status"][task["id"]]
    for line in plan["resources"]:
        if line["id"] in effects.get("resource_actual", {}):
            line["actual"] = effects["resource_actual"][line["id"]]
    s.put("plan", "current", plan)
    for raw in effects.get("outbox", []):
        s.put("outbox", raw["id"], m.OutboundMessage.model_validate(raw))
    for item_id in effects.get("waiting_close", []):
        if item := s.get("waiting", item_id):
            s.put("waiting", item_id, {**item, "status": "done"})
    return m.Decision(
        id=f"d-{request.flag_id}-{request.action}", flag_id=request.flag_id, action=request.action,
        proposal_id=request.proposal_id, reason=request.reason, decided_by=request.decided_by,
        decided_at=pipeline.now(), standing_rule=request.standing_rule,
        authorization_id=request.authorization_id,
    )
