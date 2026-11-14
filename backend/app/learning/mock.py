"""Mock: stores a standing rule when the decision asks for one."""
from app.core import models as m
from app.core.store import store


def on_decision(decision: m.Decision) -> None:
    if decision.standing_rule:
        store().put("rules", decision.id, {"decision_id": decision.id, "flag_id": decision.flag_id, "action": decision.action})
