"""Read-only, project-scoped snapshots of actual pipeline work.

This lock is independent of the store and pipeline locks, so a reader never waits for extraction or delivery.
Snapshots describe work in this process only; they are not a reconstructed history of old stored events.
"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock

from fastapi import FastAPI

from app.core import config
from app.core import models as m

STAGES = (
    ("transcribe", "Transcribing voice note"),
    ("readback", "Checking voice confirmation"),
    ("extract", "Reading message and attachments"),
    ("record", "Updating project record"),
    ("drawings", "Comparing drawings"),
    ("rules", "Checking work and schedule"),
    ("answer", "Preparing an answer"),
    ("delivery", "Preparing and delivering messages"),
)
MAX_JOBS = 160
_lock = RLock()
_projects: dict[str, dict[str, dict]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _namespace() -> str:
    return str(config.data_dir().resolve())


def _new(event: m.InboundEvent) -> dict:
    return {
        "id": event.id, "event_id": event.id, "channel": event.channel,
        "sender": event.sender, "subject": event.subject, "status": "queued",
        "started_at": None, "updated_at": _now(), "finished_at": None, "stage": None,
        "stages": [{"id": key, "label": label, "status": "pending", "started_at": None,
                    "finished_at": None} for key, label in STAGES],
        "result": {"flag_ids": [], "diff_ids": [], "message_ids": [], "record_ids": [],
                   "fact_ids": [], "answer_id": None},
    }


def _insert(namespace: str, event: m.InboundEvent) -> dict:
    jobs = _projects.setdefault(namespace, {})
    jobs.pop(event.id, None)
    jobs[event.id] = _new(event)
    while len(jobs) > MAX_JOBS:
        # Prefer retiring a finished snapshot over hiding live work.
        oldest = next((key for key, job in jobs.items() if job["finished_at"]), next(iter(jobs)))
        del jobs[oldest]
    return jobs[event.id]


def enqueue(event: m.InboundEvent) -> None:
    namespace = _namespace()
    with _lock:
        previous = _projects.get(namespace, {}).get(event.id)
        if previous is None or previous["status"] in ("completed", "failed"):
            _insert(namespace, event)


def snapshot() -> dict:
    namespace = _namespace()
    with _lock:
        jobs = sorted(_projects.get(namespace, {}).values(), key=lambda job: job["updated_at"], reverse=True)
        return {"jobs": deepcopy(jobs)}


def clear() -> None:
    namespace = _namespace()
    with _lock:
        _projects.pop(namespace, None)


def install(app: FastAPI) -> None:
    # Additive local API; the product's frozen OpenAPI contract stays unchanged.
    app.add_api_route("/api/activity", snapshot, methods=["GET"], include_in_schema=False)


class Job:
    def __init__(self, event: m.InboundEvent):
        self.namespace = _namespace()
        with _lock:
            previous = _projects.get(self.namespace, {}).get(event.id)
            self.data = previous if previous and previous["started_at"] is None else _insert(self.namespace, event)
            self.data.update(status="processing", started_at=_now(), updated_at=_now())

    def stage(self, key: str) -> None:
        with _lock:
            at = _now()
            for stage in self.data["stages"]:
                if stage["status"] == "processing":
                    stage.update(status="completed", finished_at=at)
                if stage["id"] == key:
                    stage.update(status="processing", started_at=at)
            self.data.update(stage=key, updated_at=at)

    def skip(self, key: str) -> None:
        with _lock:
            for stage in self.data["stages"]:
                if stage["id"] == key:
                    stage.update(status="skipped", finished_at=_now())

    def result(self, result: m.IngestResult, *, waiting: bool = False, screened: bool = False) -> None:
        with _lock:
            at = _now()
            self.data["result"] = {
                "flag_ids": [row.id for row in result.flags], "diff_ids": [row.id for row in result.diffs],
                "message_ids": [row.id for row in result.outbox], "record_ids": [row.id for row in result.record],
                "fact_ids": [row.id for row in result.facts], "answer_id": result.answer.id if result.answer else None,
                "outcome": "awaiting_confirmation" if waiting else "handled_readback" if screened else "processed",
                "delivery_failed_ids": [row.id for row in result.outbox if row.status == "failed"],
                "delivery_queued_ids": [row.id for row in result.outbox if row.status == "queued"],
                "delivery_simulated_ids": [row.id for row in result.outbox if row.status == "simulated"],
            }
            for stage in self.data["stages"]:
                if stage["status"] == "processing":
                    stage.update(status="waiting" if waiting else "completed", finished_at=None if waiting else at)
                elif stage["status"] == "pending" and not waiting:
                    stage.update(status="skipped", finished_at=at)
            self.data.update(status="queued" if waiting else "completed", updated_at=at,
                             finished_at=None if waiting else at, stage="readback" if waiting else "completed")

    def fail(self) -> None:
        with _lock:
            at = _now()
            current = next((stage for stage in self.data["stages"] if stage["status"] == "processing"), None)
            if current:
                current.update(status="failed", finished_at=at)
            label = current["label"] if current else "Processing"
            self.data.update(status="failed", updated_at=at, finished_at=at,
                             error=f"{label} failed. Processing can be retried.")
