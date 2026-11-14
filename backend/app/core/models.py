"""Shared data shapes. contracts/openapi.json is generated from these models and frozen."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


Channel = Literal["telegram", "email", "whatsapp", "schedule", "replay", "machine"]
FactType = Literal[
    "drawing_revision",
    "work_planned",
    "work_started",
    "inspection_scheduled",
    "inspection_moved",
    "inspection_passed",
    "delivery_planned",
    "delivery_actual",
    "equipment_planned",
    "equipment_actual",
    "acknowledgement",
    "question",
    "other",
]
FlagType = Literal["stale_drawing", "unacknowledged_change", "out_of_sequence", "plan_deviation"]
FlagStatus = Literal["open", "held", "released", "dismissed", "resolved"]
ActionType = Literal["hold_work", "release_work", "reschedule", "notify_crew", "request_ack", "dismiss"]


class Attachment(Model):
    kind: Literal["audio", "image", "pdf", "file"]
    name: str
    url: str | None = None
    media_type: str | None = None


class InboundEvent(Model):
    """C1. One message, email, voice note or schedule update, as a channel delivers it."""

    id: str
    channel: Channel
    sent_at: datetime
    received_at: datetime
    sender: str
    sender_role: str | None = None
    thread: str | None = None
    subject: str | None = None
    text: str = ""
    transcript: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)


class Fact(Model):
    """C2. One statement extracted from an event. `data` holds the fields of its type (contracts/README.md)."""

    id: str
    event_id: str
    type: FactType
    subject: str
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    quote: str | None = None


class RecordEntry(Model):
    id: str
    at: datetime
    kind: Literal["change", "decision", "notice", "acknowledgement", "flag", "answer", "info"]
    title: str
    detail: str | None = None
    actor: str | None = None
    source_event_ids: list[str] = Field(default_factory=list)
    refs: dict[str, str] = Field(default_factory=dict)


class WaitingItem(Model):
    id: str
    on: str
    what: str
    since: datetime
    due: datetime | None = None
    status: Literal["open", "done"] = "open"
    source_event_ids: list[str] = Field(default_factory=list)


class RecordUpdate(Model):
    entries: list[RecordEntry] = Field(default_factory=list)
    waiting_open: list[WaitingItem] = Field(default_factory=list)
    waiting_close: list[str] = Field(default_factory=list)


class Evidence(Model):
    event_id: str
    channel: Channel
    sender: str
    at: datetime
    quote: str
    attachment_url: str | None = None


class Flag(Model):
    """C4. A problem found before work starts, with the sources that prove it."""

    id: str
    type: FlagType
    severity: Literal["high", "medium", "low"]
    title: str
    summary: str
    status: FlagStatus = "open"
    raised_at: datetime
    work_starts_at: datetime | None = None
    affected: dict[str, str] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    numbers: dict[str, float] | None = None
    diff_id: str | None = None
    proposal_id: str | None = None


class DiffRegion(Model):
    """A changed area, as fractions of the sheet's width and height (0 to 1)."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)
    kind: Literal["added", "removed", "moved"]
    label: str | None = None


class DrawingDiff(Model):
    """C5. What changed between two revisions of one sheet."""

    id: str
    sheet: str
    title: str
    from_rev: str
    to_rev: str
    before_url: str
    after_url: str
    overlay_url: str
    before_geometry_url: str | None = None
    after_geometry_url: str | None = None
    regions: list[DiffRegion] = Field(default_factory=list)
    summary: str | None = None


class Task(Model):
    id: str
    name: str
    unit: str | None = None
    crew: str
    start: datetime
    end: datetime
    depends_on: list[str] = Field(default_factory=list)
    requires_inspection: str | None = None
    status: Literal["planned", "on_hold", "in_progress", "done"] = "planned"


class ResourceLine(Model):
    id: str
    item: str
    kind: Literal["delivery", "equipment", "crew"]
    date: datetime
    planned: float
    actual: float | None = None
    unit: str = "count"


class Plan(Model):
    """C8. The schedule and the planned resources."""

    tasks: list[Task] = Field(default_factory=list)
    resources: list[ResourceLine] = Field(default_factory=list)
    handover: datetime


class TaskShift(Model):
    task_id: str
    name: str
    crew: str
    old_start: datetime
    old_end: datetime
    new_start: datetime
    new_end: datetime


class Proposal(Model):
    """C6. A suggested action. Nothing with consequences runs before the superintendent decides."""

    id: str
    flag_id: str | None = None
    action: ActionType
    summary: str
    params: dict[str, Any] = Field(default_factory=dict)
    shifts: list[TaskShift] = Field(default_factory=list)
    handover_old: datetime | None = None
    handover_new: datetime | None = None
    basis: Literal["calculated", "rule", "assistant"]
    requires_human: bool = True
    status: Literal["proposed", "accepted", "rejected"] = "proposed"


class DecisionRequest(Model):
    flag_id: str
    action: ActionType
    proposal_id: str | None = None
    reason: str | None = None
    decided_by: str = "superintendent"
    standing_rule: bool = False
    authorization_id: str | None = None


class Decision(Model):
    id: str
    flag_id: str
    action: ActionType
    proposal_id: str | None = None
    reason: str | None = None
    decided_by: str
    decided_at: datetime
    standing_rule: bool = False
    authorization_id: str | None = None


class OutboundMessage(Model):
    """C7. A message Aurora sends to a crew or person through a channel."""

    id: str
    channel: Channel
    to: str
    text: str
    media_url: str | None = None
    buttons: list[str] = Field(default_factory=list)
    reason: str
    in_reply_to: str | None = None
    created_at: datetime
    status: Literal["queued", "sent", "failed", "simulated"] = "queued"


class Answer(Model):
    id: str
    event_id: str
    question: str
    text: str
    basis: Literal["record", "standing_rule", "unknown"]
    sources: list[Evidence] = Field(default_factory=list)
    escalated: bool = False
    created_at: datetime


StartVerdict = Literal["yes", "no", "unknown"]
StartReasonKind = Literal[
    "work_on_hold",
    "superseded_drawing",
    "inspection_open",
    "drawing_not_confirmed",
    "resource_deviation",
    "dependency_open",
    "not_in_record",
    "unit_occupied",
]
ReadinessStatus = Literal["blocked", "at_risk", "ready", "unknown"]
PatternKind = Literal["late_change", "late_confirmation", "repeat_flag", "dismissed_flags"]


class StartReason(Model):
    """D1. One thing that stands in the way of starting a task, with the events that prove it."""

    kind: StartReasonKind
    text: str
    blocking: bool
    sources: list[Evidence] = Field(default_factory=list)
    flag_id: str | None = None


class StartCheckRequest(Model):
    """D1. A person, an agent or a robot asks whether it may start a task before it does."""

    asked_by: str
    task_id: str | None = None
    unit: str | None = None
    activity: str | None = None


class StartCheck(Model):
    id: str
    asked_by: str
    task_id: str | None = None
    unit: str | None = None
    activity: str | None = None
    allowed: StartVerdict
    summary: str
    reasons: list[StartReason] = Field(default_factory=list)
    checked_at: datetime


class ReadinessItem(Model):
    task_id: str
    name: str
    unit: str | None = None
    crew: str
    start: datetime
    status: ReadinessStatus
    reasons: list[StartReason] = Field(default_factory=list)


class Readiness(Model):
    """D2. Tomorrow on site: every task of one day, each with the start check's answer."""

    day: date
    generated_at: datetime
    items: list[ReadinessItem] = Field(default_factory=list)
    briefings: list[OutboundMessage] = Field(default_factory=list)


class StandingRule(Model):
    """D3. What the superintendent taught Aurora by deciding, applied to later similar cases."""

    id: str
    text: str
    scope: dict[str, Any] = Field(default_factory=dict)
    decision_id: str
    decided_by: str
    decided_at: datetime
    applied_count: int = 0


class Pattern(Model):
    """D3. What the record shows when it is counted. Never a forecast."""

    id: str
    kind: PatternKind
    statement: str
    count: int
    total: int
    examples: list[str] = Field(min_length=1)
    suggestion: str | None = None


class Insights(Model):
    generated_at: datetime
    demo_data: bool = True
    standing_rules: list[StandingRule] = Field(default_factory=list)
    patterns: list[Pattern] = Field(default_factory=list)


class AuthorizationApplication(Model):
    """D4. One flag Aurora held by itself under an authorization."""

    decision_id: str
    flag_id: str
    record_entry_id: str
    at: datetime


AuthorizationStatus = Literal["active", "revoked", "superseded"]


class Authorization(Model):
    """D4. The right to hold one kind of case alone, earned from three matching decisions and revocable."""

    id: str
    action: ActionType
    flag_type: FlagType
    scope: dict[str, str] = Field(default_factory=dict)
    statement: str
    rule_id: str
    evidence_decision_ids: list[str] = Field(min_length=3, max_length=3)
    evidence_flag_ids: list[str] = Field(min_length=3, max_length=3)
    granted_by: str
    granted_at: datetime
    status: AuthorizationStatus = "active"
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    superseded_by: str | None = None
    applications: list[AuthorizationApplication] = Field(default_factory=list)


class AutonomySuggestion(Model):
    """D4. What the record supports granting, computed on read and never stored."""

    id: str
    action: ActionType
    flag_type: FlagType
    scope: dict[str, str] = Field(default_factory=dict)
    statement: str
    evidence_decision_ids: list[str] = Field(min_length=3, max_length=3)
    evidence_flag_ids: list[str] = Field(min_length=3, max_length=3)
    last_decided_at: datetime


class Autonomy(Model):
    generated_at: datetime
    suggestions: list[AutonomySuggestion] = Field(default_factory=list)
    authorizations: list[Authorization] = Field(default_factory=list)
    automatic_holds_today: int = 0
    daily_limit: int = 5


class AutonomyGrantRequest(Model):
    suggestion_id: str
    granted_by: str


class AutonomyRevokeRequest(Model):
    revoked_by: str


class Machine(Model):
    """D5. A registered machine: the name it sends, the units it works in and the sheets it loads."""

    id: str
    kind: Literal["robot", "drone", "sensor", "agent"]
    name: str
    units: list[str] = Field(default_factory=list)
    sheets: list[str] = Field(default_factory=list)
    simulated: bool = True


class MachineNotice(Model):
    """D5. A drawing change waiting for one machine to confirm the revision it loaded."""

    id: str
    machine_id: str
    sheet: str
    revision: str
    replaces: str | None = None
    units: list[str] = Field(default_factory=list)
    change: str | None = None
    diff_id: str | None = None
    geometry_url: str | None = None
    sent_at: datetime
    received_at: datetime | None = None
    due: datetime | None = None
    waiting_id: str


class MachineConfirmRequest(Model):
    sheet: str
    revision: str


class MachineConfirmation(Model):
    id: str
    machine_id: str
    sheet: str
    revision: str
    current_revision: str
    status: Literal["confirmed", "outdated"]
    confirmed_at: datetime
    event_id: str
    waiting_id: str | None = None


class MeasuredLine(Model):
    """Where a wall stands, in millimetres in the sheet's coordinates (C5)."""

    x1: float
    y1: float
    x2: float
    y2: float


class MachineReportRequest(Model):
    """D5. What a machine found, as measured fields only. There is no free text."""

    report_id: str
    kind: Literal["wall", "delivery"]
    observed_at: datetime
    unit: str | None = None
    sheet: str | None = None
    wall: str | None = None
    line: MeasuredLine | None = None
    item: str | None = None
    count: float | None = None


class MachineReportResult(Model):
    report_id: str
    machine_id: str
    event_id: str
    duplicate: bool = False
    status: Literal["understood", "not_understood"]
    reason: str | None = None
    matches_revision: str | None = None
    facts: list[Fact] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)


class Project(Model):
    id: str
    name: str
    description: str
    units: list[str]
    sheets: list[str]
    crews: list[str]
    demo_data: bool = True


class IngestResult(Model):
    event_id: str
    duplicate: bool = False
    facts: list[Fact] = Field(default_factory=list)
    record: list[RecordEntry] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    diffs: list[DrawingDiff] = Field(default_factory=list)
    outbox: list[OutboundMessage] = Field(default_factory=list)
    answer: Answer | None = None


class CommandRequest(Model):
    text: str


class CommandResponse(Model):
    message: str
    proposal: Proposal | None = None


class Health(Model):
    status: Literal["ok"]
    data_dir: str
    version: str
    mocks: dict[str, bool]
