"""Mock: standing rules counted from the store, patterns from mocks/scenario.json."""
from datetime import datetime, timezone

from app.core import models as m
from app.core import scenario
from app.core.store import store


def _time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _generated_at() -> datetime:
    times = [at for at in (_time(entry.get("at")) for entry in store().list("record")) if at is not None]
    return max(times) if times else datetime.now(timezone.utc)


def _text(rule: dict) -> str:
    canned = scenario.load()["insights"]["rule_texts"]
    flag_id = rule.get("flag_id") or ""
    if flag_id in canned:
        return canned[flag_id]
    flag = store().get("flags", flag_id) or {}
    return flag.get("title") or "A decision the superintendent marked for similar cases."


def _rule(rule: dict, answers: list[dict]) -> m.StandingRule:
    decision_id = rule.get("decision_id") or rule.get("id") or ""
    decision = store().get("decisions", decision_id) or {}
    decided_at = _time(rule.get("decided_at") or decision.get("decided_at")) or _generated_at()
    decided_by = rule.get("decided_by") or decision.get("decided_by") or "superintendent"
    # Answers carry no rule id, and the demo answers keep their scenario time while a decision is stamped with
    # the wall clock, so a time filter would count nothing here. The mock counts every answer that rests on a
    # standing rule; the real module (F69) attributes each application to the rule it came from.
    applied = [answer for answer in answers if answer.get("basis") == "standing_rule"]
    return m.StandingRule(
        id=rule.get("id") or f"rule-{decision_id}", text=_text(rule), scope=rule.get("scope") or {},
        decision_id=decision_id, decided_by=decided_by, decided_at=decided_at, applied_count=len(applied),
    )


# The kinds of record entry each pattern is about, for the fallback when a canned example is not in the record.
EXAMPLES_OF = {
    "late_change": ("change",),
    "late_confirmation": ("change", "notice"),
    "repeat_flag": ("flag",),
    "dismissed_flags": ("flag", "decision"),
}


def _patterns() -> list[m.Pattern]:
    """Canned numbers, but examples that exist. A real data field moves the record ids, so a canned example
    would otherwise link to nothing; the pattern is dropped when the record holds nothing of its kind."""
    entries = store().list("record")
    known = {entry["id"] for entry in entries}
    patterns: list[m.Pattern] = []
    for raw in scenario.load()["insights"]["patterns"]:
        pattern = m.Pattern.model_validate(raw)
        examples = [example for example in pattern.examples if example in known]
        if not examples:
            kinds = EXAMPLES_OF.get(pattern.kind, ())
            examples = [entry["id"] for entry in entries if entry.get("kind") in kinds][-2:]
        if examples:
            patterns.append(pattern.model_copy(update={"examples": examples}))
    return patterns


def summary() -> m.Insights:
    project = store().get("project", "current") or {}
    answers = store().list("answers")
    return m.Insights(
        generated_at=_generated_at(),
        demo_data=bool(project.get("demo_data", True)),
        standing_rules=[_rule(rule, answers) for rule in store().list("rules")],
        patterns=_patterns(),
    )
