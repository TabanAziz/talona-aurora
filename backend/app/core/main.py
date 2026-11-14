"""HTTP API (contracts/openapi.json) and the built frontend, served by one process."""
import logging
from html import escape
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import activity, demodata
from app.workspace import install as install_workspace
from app.readiness import scheduler as briefing_scheduler
from app.readiness import acknowledgement as briefing_ack
from app.telegram import webhook as telegram_sender
from app.telegram import polling as telegram_polling

from . import config, mailbox, pipeline, site
from . import models as m
from .registry import area, is_mock
from .store import store

config.load_dotenv()

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    pipeline.ensure_ready()
    task = mailbox.start()
    telegram_task = telegram_polling.start()
    briefing_task = briefing_scheduler.start()
    try:
        yield
    finally:
        await briefing_scheduler.stop(briefing_task)
        await telegram_polling.stop(telegram_task)
        await mailbox.stop(task)


app = FastAPI(title="Aurora API", version=config.VERSION, lifespan=lifespan)


def _one(collection: str, doc_id: str) -> dict:
    doc = store().get(collection, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"{collection} {doc_id} not found")
    return doc


@app.get("/health", response_model=m.Health)
def health():
    mocks = {name: is_mock(name) for name in config.AREAS}
    mocks.update({name: config.external_is_mock(name) for name in config.EXTERNAL})
    # The one switch that is neither an area nor an external service, reported here so a read-only check can
    # tell an operator whether a visitor would be answered at all.
    mocks["guest_mode"] = config.flag("GUEST_MODE") is True
    return m.Health(status="ok", data_dir=str(config.data_dir()), version=config.build_version(), mocks=mocks)


@app.get("/api/project", response_model=m.Project)
def get_project():
    return _one("project", "current")


@app.post("/api/ingest", response_model=m.IngestResult)
def post_ingest(event: m.InboundEvent):
    return pipeline.ingest(event)


@app.get("/api/events", response_model=list[m.InboundEvent])
def list_events():
    return store().list("events")


@app.get("/api/events/{event_id}", response_model=m.InboundEvent)
def get_event(event_id: str):
    return _one("events", event_id)


@app.get("/api/record", response_model=list[m.RecordEntry])
def list_record():
    return sorted(store().list("record"), key=lambda e: e["at"], reverse=True)


@app.get("/api/waiting", response_model=list[m.WaitingItem])
def list_waiting():
    return [w for w in store().list("waiting") if w["status"] == "open"]


@app.get("/api/flags", response_model=list[m.Flag])
def list_flags():
    return store().list("flags")


@app.get("/api/flags/{flag_id}", response_model=m.Flag)
def get_flag(flag_id: str):
    return _one("flags", flag_id)


@app.get("/api/diffs", response_model=list[m.DrawingDiff])
def list_diffs():
    return store().list("diffs")


@app.get("/api/diffs/{diff_id}", response_model=m.DrawingDiff)
def get_diff(diff_id: str):
    return _one("diffs", diff_id)


@app.get("/api/plan", response_model=m.Plan)
def get_plan():
    return _one("plan", "current")


@app.get("/api/proposals", response_model=list[m.Proposal])
def list_proposals():
    return store().list("proposals")


@app.get("/api/proposals/{proposal_id}", response_model=m.Proposal)
def get_proposal(proposal_id: str):
    return _one("proposals", proposal_id)


def _refuse_machine(name: str) -> None:
    """A machine is told, confirms, reports and asks; whatever has consequences stays with a person."""
    # Case-blind, so "Layout-Robot-1" cannot slip past the rule a machine name is written in.
    if name.strip().lower() in {machine.id.lower() for machine in area("machine").machines()}:
        raise HTTPException(status_code=409, detail="A machine cannot decide. Ask the superintendent.")


@app.post("/api/decisions", response_model=m.Decision)
def post_decision(request: m.DecisionRequest):
    _refuse_machine(request.decided_by)
    try:
        return pipeline.decide(request)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"flag {request.flag_id} not found") from None
    except pipeline.DecisionRefused as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None


@app.get("/api/decisions", response_model=list[m.Decision])
def list_decisions():
    return store().list("decisions")


@app.get("/api/outbox", response_model=list[m.OutboundMessage])
def list_outbox():
    return store().list("outbox")


@app.get("/api/answers", response_model=list[m.Answer])
def list_answers():
    return store().list("answers")


def _task_name(task_id: str | None) -> str:
    plan = store().get("plan", "current") or {}
    for task in plan.get("tasks", []):
        if task.get("id") == task_id:
            return task.get("name") or str(task_id)
    return task_id or "a task"


@app.post("/api/context/can-start", response_model=m.StartCheck)
def post_can_start(request: m.StartCheckRequest):
    """A person, an agent or a robot asks before it starts. The answer never changes the site."""
    gate = area("gate")
    # The asker's name lands in the record and the daily mail, so a bad one is refused before anything is written.
    problem = getattr(gate, "asker_problem", lambda _: None)(request.asked_by)
    if problem is not None:
        raise HTTPException(status_code=422, detail=problem)
    check: m.StartCheck = gate.check(request)
    store().put("checks", check.id, check)
    store().put("record", f"r-check-{check.id}", m.RecordEntry(
        id=f"r-check-{check.id}", at=check.checked_at, kind="answer",
        title=f"{check.asked_by} asked to start {_task_name(check.task_id)}: {check.allowed}",
        detail=check.summary, actor="Aurora", refs={"check": check.id},
    ))
    return check


@app.get("/api/context/checks", response_model=list[m.StartCheck])
def list_checks():
    """Newest first. Checks share the time of the latest event, so insertion order breaks the tie."""
    return list(reversed(store().list("checks")))


@app.get("/api/readiness", response_model=m.Readiness)
def get_readiness(day: date | None = None):
    return area("readiness").evaluate(day)


@app.post("/api/readiness/run", response_model=m.Readiness)
def post_readiness_run(day: date | None = None):
    return area("readiness").run(day)


@app.get("/api/insights", response_model=m.Insights)
def get_insights():
    return area("insights").summary()


@app.get("/api/autonomy", response_model=m.Autonomy)
def get_autonomy():
    return area("autonomy").suggest()


@app.post("/api/autonomy/grant", response_model=m.Authorization)
def post_autonomy_grant(request: m.AutonomyGrantRequest):
    _refuse_machine(request.granted_by)
    try:
        return area("autonomy").grant(request)
    except KeyError:
        raise HTTPException(status_code=404, detail="No suggestion with that id. Nothing was granted.") from None
    except ValueError as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None


@app.post("/api/autonomy/{authorization_id}/revoke", response_model=m.Authorization)
def post_autonomy_revoke(authorization_id: str, request: m.AutonomyRevokeRequest):
    _refuse_machine(request.revoked_by)
    try:
        return area("autonomy").revoke(authorization_id, request.revoked_by)
    except KeyError:
        raise HTTPException(status_code=404, detail="No authorization with that id.") from None
    except ValueError as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None


def _unknown_machine(machine_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No machine named {machine_id} is registered. Nothing was stored.")


@app.get("/api/machines", response_model=list[m.Machine])
def list_machines():
    return area("machine").machines()


@app.get("/api/machines/{machine_id}/notices", response_model=list[m.MachineNotice])
def list_machine_notices(machine_id: str):
    """Fetching is how a machine receives a notice: the first fetch records the time it was received."""
    try:
        return area("machine").notices(machine_id)
    except KeyError:
        raise _unknown_machine(machine_id) from None


@app.post("/api/machines/{machine_id}/confirm", response_model=m.MachineConfirmation)
def post_machine_confirm(machine_id: str, request: m.MachineConfirmRequest):
    try:
        return area("machine").confirm(machine_id, request)
    except KeyError:
        raise _unknown_machine(machine_id) from None
    except ValueError as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None


@app.post("/api/machines/{machine_id}/reports", response_model=m.MachineReportResult)
def post_machine_report(machine_id: str, request: m.MachineReportRequest):
    """A report is measured fields only; code turns it into facts, no model reads it."""
    try:
        return area("machinereport").report(machine_id, request)
    except KeyError:
        raise _unknown_machine(machine_id) from None


@app.post("/api/command", response_model=m.CommandResponse)
def post_command(request: m.CommandRequest):
    return pipeline.command(request.text)


@app.post("/api/demo/reset", response_model=m.Project)
def demo_reset():
    pipeline.reset()
    return _one("project", "current")


SHIFTED_REPLAY = (
    "Play next event cannot replay the prepared scenario with USE_MOCK_LLM=true while DEMO_ANCHOR moves the demo "
    "day, because the recorded model answers only fit the scenario's own dates, so unset DEMO_ANCHOR or set "
    "USE_MOCK_LLM=false."
)


@app.post("/api/demo/next", response_model=m.IngestResult | None)
def demo_next():
    """Ingest the next event of the prepared scenario. Returns null when every event was played."""
    # The replay key hashes the prompt, which holds the shifted dates, so no recorded answer can ever match.
    # With the extraction itself on its mock no recorded answer is needed, and the fallback walk still plays.
    if config.external_is_mock("llm") and not is_mock("extract") and demodata.shift_days() != 0:
        raise HTTPException(status_code=409, detail=SHIFTED_REPLAY)
    try:
        return pipeline.play_next()
    except pipeline.MissingModelAnswer as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


def _ingest_all(events: list[m.InboundEvent]) -> dict[str, int]:
    results = [pipeline.ingest(event) for event in events]
    return {"received": len(results), "ingested": sum(1 for r in results if not r.duplicate)}


def _from_telegram(request: Request) -> None:
    # Read from the raw request, not as a declared header, so the published API contract keeps its shape.
    if not telegram_sender.allowed(request.headers.get(telegram_sender.HEADER)):
        raise HTTPException(status_code=403, detail="webhook secret missing or wrong")


@app.post("/api/channels/telegram/webhook", dependencies=[Depends(_from_telegram)])
def telegram_webhook(update: dict[str, Any], background: BackgroundTasks) -> dict[str, int]:
    from app.workspace.channels import accepts_telegram
    if not accepts_telegram(update):
        return {"received": 0, "ingested": 0}
    events = area("telegram").parse(update)
    if not events:
        reason = telegram_sender.drop_reason(update)
        if reason:
            log.info("telegram: update %s dropped: %s", telegram_sender.update_id(update), reason)
        return {"received": 0, "ingested": 0}
    if len(events) == 1:
        result = briefing_ack.accept(update.get("callback_query"), events[0])
        if result is not None:
            return {"received": 1, "ingested": int(not result.duplicate)}
    # Telegram retries an update that is not answered in time, so the answer comes before the model runs. The
    # stored event row is the duplicate guard while the work is queued.
    accepted = [pipeline.accept(event) for event in events]
    for event, result in zip(events, accepted):
        if not result.duplicate:
            background.add_task(_run_stored, event.id)
    return {"received": len(accepted), "ingested": sum(1 for r in accepted if not r.duplicate)}


def _run_stored(event_id: str) -> None:
    """A background failure must not look like an answered update, so it is logged with the event it was for."""
    try:
        pipeline.run_stored(event_id)
    except Exception as error:
        log.error("telegram: the pipeline failed for %s: %s", event_id, type(error).__name__)


@app.post("/api/channels/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> dict[str, int]:
    form = dict(await request.form())
    return _ingest_all(area("whatsapp").parse(form))


@app.post("/api/channels/email/poll")
def email_poll() -> dict[str, int]:
    return _ingest_all(area("email").poll())


@app.post("/api/channels/telegram/poll", include_in_schema=False)
def telegram_poll() -> dict:
    return telegram_polling.poll_once()


activity.install(app)
install_workspace(app)

app.mount("/media/mock", StaticFiles(directory=config.ROOT / "mocks" / "assets", check_dir=False), name="mock-media")
_files = config.data_dir() / "files"
_files.mkdir(parents=True, exist_ok=True)
app.mount("/media/files", StaticFiles(directory=_files), name="files")

_dist = config.ROOT / "frontend" / "dist"
if (_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    """Serve the built single-page app; unknown paths fall back to index.html so client routes work."""
    if path.startswith(("api/", "media/")):
        raise HTTPException(status_code=404, detail="not found")
    target = (_dist / path).resolve()
    index = _dist / "index.html"
    if path and target.is_file() and _dist.resolve() in target.parents and target != index.resolve():
        return FileResponse(target)
    if not index.is_file():
        raise HTTPException(status_code=503, detail="frontend is not built. Run: pnpm -C frontend build")
    html = index.read_text(encoding="utf-8")
    metadata = f'<meta name="site-timezone" content="{escape(site.zone().key, quote=True)}">'
    return HTMLResponse(html.replace("<head>", "<head>" + metadata, 1))


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=config.port(), log_level="warning")


if __name__ == "__main__":
    main()
