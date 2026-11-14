import { projectApiUrl } from "../../api/workspace";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, request as sendRequest, type DrawingDiff, type StartCheck, type StartCheckRequest } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { loadGeometry, type Geometry } from "../../components/plan3d/geometry";
import { webglAvailable } from "../../components/plan3d/scene";
import { splitFloors, type FloorPlan } from "../../components/plan3d/floors";
import { Badge } from "../../components/Badge";
import { formatTime } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import { ASKED_BY, SHEET, levelUnits, reasonsOf, sourcesOf, startRequest, switchText, type UnitWork } from "./layout";
import { takeNotices, confirmDrawing, type Load } from "./notices";
import { drawingsApi } from "../drawings/api";
import { createRobotScene, type RobotScene, type RobotState } from "./robotScene";
import { Immersive } from "../../components/immersive/Immersive";
import "./robot.css";

const STALL_MS = 700;
const POLL_MS = 2500;

interface Setup {
  diff: DrawingDiff | null;
  before: Geometry;
  after: Geometry;
  units: string[];
  machineId: string;
  initial: boolean;
}

type Phase = "ready" | "asking" | "waiting" | "done";
type Outcome = "chalked" | "waiting" | "error";

interface LogEntry {
  at: string;
  unit: string;
  allowed: string;
}

async function loadSetup(): Promise<Setup | null> {
  const [diffs, project, machines] = await Promise.all([api.diffs(), api.project(), api.machines()]);
  const machine = machines.find(item => item.id === ASKED_BY && item.kind === "robot") ?? machines.find(item => item.kind === "robot");
  if (!machine) return null;
  const candidates = diffs
    .filter((diff) => project.sheets.includes(diff.sheet) && (machine.sheets ?? []).includes(diff.sheet) && diff.before_geometry_url && diff.after_geometry_url)
    .sort((a, b) => Number(b.sheet === SHEET) - Number(a.sheet === SHEET) || b.to_rev.localeCompare(a.to_rev));
  const diff = candidates[0];
  if (!diff || !diff.before_geometry_url || !diff.after_geometry_url) {
    const register = await drawingsApi.list();
    for (const sheet of register.sheets.filter(sheet => (machine.sheets ?? []).includes(sheet.id))) {
      const current = sheet.revisions.find(revision => revision.revision === sheet.current_revision);
      if (!current?.geometry_url) continue;
      const geometry = await loadGeometry(current.geometry_url);
      return { diff: null, before: geometry, after: geometry, units: machine.units ?? [], machineId: machine.id, initial: true };
    }
    return null;
  }
  const [before, after] = await Promise.all([
    loadGeometry(diff.before_geometry_url),
    loadGeometry(diff.after_geometry_url),
  ]);
  return { diff, before, after, units: project.units.filter(unit => (machine.units ?? []).includes(unit)), machineId: machine.id, initial: false };
}

export function Robot() {
  const forced = useForcedState();
  const setup = useQuery(loadSetup, []);

  if (forced === "empty") return <Empty>No drawing revision with geometry is available to lay out.</Empty>;
  if (setup.error) return <ErrorState message={setup.error} onRetry={setup.reload} />;
  if (setup.loading || setup.data === undefined) return <Loading rows={6} />;
  if (setup.data === null) {
    return <Empty>Register a layout robot with room and drawing coverage to use this view. <Link to="/machines">Open equipment</Link> or <Link to="/drawings">view the drawings</Link>.</Empty>;
  }
  return <RobotFloors setup={setup.data} />;
}

function RobotFloors({ setup }: { setup: Setup }) {
  const floors = useMemo(() => splitFloors(setup.after), [setup.after]);
  const [level, setLevel] = useState(() => floors.find(floor => floor.rooms.some(room => setup.units.includes(room.label)) && floor.walls.some(wall => wall.kind === "partition"))?.level ?? floors[0]?.level ?? "");
  const current = floors.find(floor => floor.level === level) ?? floors[0];
  const previousFloors = splitFloors(setup.before);
  const previous = previousFloors.find(floor => floor.level === current.level)
    ?? (previousFloors.length === 1 && previousFloors[0].level === "" ? previousFloors[0] : undefined);
  function onFloor(geometry: Geometry, floor?: FloorPlan): Geometry {
    const ids = new Set(floor?.walls.map(wall => wall.id));
    return { ...geometry, walls: floor?.walls ?? [], rooms: floor?.rooms ?? [], openings: floor?.openings ?? [], changed: geometry.changed?.filter(id => ids.has(id)) };
  }
  return <>{floors.length > 1 && <label className="drawings-revision-select">Layout floor<select value={current.level} onChange={event => setLevel(event.target.value)}>{floors.map(floor => <option key={floor.level} value={floor.level}>Level {floor.level}</option>)}</select></label>}<RobotBody key={current.level} setup={{ ...setup, before: onFloor(setup.before, previous), after: onFloor(setup.after, current) }} /></>;
}

function RobotBody({ setup }: { setup: Setup }) {
  const [params] = useSearchParams();
  const stepMode = params.get("step") === "1";
  const units = useMemo(() => levelUnits(setup.after, setup.units), [setup.after, setup.units]);
  const changedIds = useMemo(() => new Set(setup.after.changed ?? []), [setup.after]);

  const [revision, setRevision] = useState<"before" | "after">("before");
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [answers, setAnswers] = useState<Record<string, StartCheck>>({});
  const [marked, setMarked] = useState<string[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [cursor, setCursor] = useState(0);
  const [phase, setPhase] = useState<Phase>(setup.initial ? "ready" : "asking");
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [request, setRequest] = useState<StartCheckRequest | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [switched, setSwitched] = useState<string | null>(null);
  const [load, setLoad] = useState<Load | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [waitedMs, setWaitedMs] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [webgl] = useState(() => webglAvailable());
  const [fallback, setFallback] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<RobotScene | null>(null);
  const busyRef = useRef(false);
  const revisionRef = useRef(revision);
  const outcomesRef = useRef(outcomes);
  const waitingSince = useRef<number | null>(null);
  const signature = useRef<string | null>(null);
  revisionRef.current = revision;
  outcomesRef.current = outcomes;

  const geometry = revision === "before" ? setup.before : setup.after;
  const currentUnit: UnitWork | null = cursor < units.length ? units[cursor] : null;
  const waitingUnits = units.filter((unit) => outcomes[unit.name] === "waiting" || outcomes[unit.name] === "error");
  const chalkedUnits = units.filter((unit) => outcomes[unit.name] === "chalked");
  const lastEntry = log[log.length - 1];
  const lastAnswer = lastEntry ? answers[lastEntry.unit] ?? null : null;

  const record = useCallback(
    (unit: UnitWork, check: StartCheck) => {
      setAnswers((previous) => ({ ...previous, [unit.name]: check }));
      setLog((previous) => [...previous, { at: check.checked_at, unit: unit.name, allowed: check.allowed }]);
      const allowed = check.allowed === "yes";
      setOutcomes((previous) => ({ ...previous, [unit.name]: allowed ? "chalked" : "waiting" }));
      if (!allowed) return;
      setMarked((previous) => [...new Set([...previous, ...unit.walls.map((wall) => wall.id)])]);
      if (revisionRef.current === "before" && unit.walls.some((wall) => changedIds.has(wall.id))) {
        setRevision("after");
        setSwitched(switchText(setup.before.revision, setup.after.revision));
      }
    },
    [changedIds, setup.after.revision, setup.before.revision],
  );

  const ask = useCallback(
    async (unit: UnitWork) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setFailure(null);
      setRequest(startRequest(unit.name, setup.machineId));
      try {
        const check = await api.canStart(startRequest(unit.name, setup.machineId));
        record(unit, check);
      } catch (error) {
        setOutcomes((previous) => ({ ...previous, [unit.name]: "error" }));
        setFailure(error instanceof Error ? error.message : "The start check could not be answered.");
        setLog((previous) => [...previous, { at: new Date().toISOString(), unit: unit.name, allowed: "unavailable" }]);
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [record, setup.machineId],
  );

  // Before the first unit the robot takes its notices, so it works from the drawing it confirmed.
  useEffect(() => {
    let cancelled = false;
    takeNotices(setup.machineId, setup.after.sheet, setup.after.revision)
      .then((result) => {
        if (cancelled) return;
        setLoad(result);
        if (result.revision === setup.after.revision) {
          setRevision("after");
          setSwitched(switchText(setup.before.revision, setup.after.revision));
        }
      })
      .catch(() => {
        // Without its notices the robot keeps the drawing it starts with; the start check still answers for it.
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [setup.machineId, setup.after.sheet, setup.after.revision, setup.before.revision]);

  // Ask the units in order: on a no or an unknown the robot skips the unit and goes on with the next.
  useEffect(() => {
    if (!loaded || phase !== "asking" || busy) return;
    if (cursor >= units.length) {
      const anyWaiting = units.some((unit) => {
        const outcome = outcomes[unit.name];
        return outcome === "waiting" || outcome === "error";
      });
      setPhase(anyWaiting ? "waiting" : "done");
      return;
    }
    if (stepMode) return;
    const unit = units[cursor];
    const timer = window.setTimeout(() => {
      void ask(unit).then(() => setCursor((value) => value + 1));
    }, STALL_MS);
    return () => window.clearTimeout(timer);
  }, [loaded, phase, busy, cursor, units, outcomes, stepMode, ask]);

  // A skipped unit is asked again only when the flags or the waiting list changed, and finishes on a yes.
  useEffect(() => {
    if (phase !== "waiting") return;
    let cancelled = false;
    const read = async () => {
      try {
        const [flags, waitingItems] = await Promise.all([api.flags(), api.waiting()]);
        if (cancelled) return;
        const next = JSON.stringify({
          flags: flags.map((flag) => [flag.id, flag.status]),
          waiting: waitingItems.map((item) => [item.id, item.status]),
        });
        if (signature.current === null) {
          signature.current = next;
          return;
        }
        if (next === signature.current) return;
        signature.current = next;
        for (const unit of units) {
          const outcome = outcomesRef.current[unit.name];
          if (outcome !== "waiting" && outcome !== "error") continue;
          await ask(unit);
        }
      } catch {
        // A read that fails leaves the robot waiting; the next tick tries again.
      }
    };
    void read();
    const poll = window.setInterval(read, POLL_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, [phase, units, ask]);

  useEffect(() => {
    if (phase !== "waiting") return;
    if (units.length > 0 && units.every((unit) => outcomes[unit.name] === "chalked")) setPhase("done");
  }, [phase, units, outcomes]);

  useEffect(() => {
    if (phase === "waiting" && waitingSince.current === null) waitingSince.current = Date.now();
    if (phase === "done" && waitingSince.current !== null) {
      setWaitedMs(Date.now() - waitingSince.current);
      waitingSince.current = null;
    }
  }, [phase]);

  useEffect(() => {
    const element = host.current;
    if (!webgl || !element) return;
    try {
      scene.current = createRobotScene(element, setup.after);
    } catch {
      scene.current = null;
      setFallback(true);
      return;
    }
    return () => {
      scene.current?.dispose();
      scene.current = null;
    };
  }, [webgl, setup.after]);

  const stationUnit = currentUnit ?? waitingUnits[0] ?? null;
  const sceneState: RobotState = phase === "done" ? "done" : phase === "waiting" || failure ? "stopped" : "running";

  useEffect(() => {
    scene.current?.update(geometry, revision === "after" ? setup.before : null, marked, stationUnit?.center ?? null, sceneState);
  }, [geometry, revision, marked, stationUnit, sceneState, setup.before]);

  function step() {
    if (!loaded || busy || phase !== "asking" || !currentUnit) return;
    void ask(currentUnit).then(() => setCursor((value) => value + 1));
  }

  async function startLayout() {
    setBusy(true); setFailure(null);
    try {
      const confirmation = await confirmDrawing(setup.machineId, setup.after.sheet, setup.after.revision);
      if (confirmation.status !== "confirmed") throw new Error("A newer drawing is current. Reload before starting.");
      setLoad({ revision: confirmation.revision, notice: null, confirmation });
      setRevision("after"); setLoaded(true); setPhase("asking");
    } catch (error) { setFailure(error instanceof Error ? error.message : "The drawing could not be confirmed."); }
    finally { setBusy(false); }
  }

  async function prepareWork() {
    setBusy(true); setPlanning(true); setFailure(null);
    try {
      await sendRequest("POST", "/api/workspace/robot-programme");
      window.location.reload();
    } catch (error) { setFailure(error instanceof Error ? error.message.replace(/\bDeepSeek\b/gi, "Aurora") : "Aurora could not prepare the programme."); }
    finally { setBusy(false); setPlanning(false); }
  }

  const statusText = phase === "ready" ? "Ready to start" : phase === "asking" ? "Laying out" : phase === "waiting" ? "Waiting" : "Done";
  const statusState = phase === "ready" ? "waiting" : phase === "asking" ? "running" : phase === "waiting" ? "waiting" : "done";
  const stoodStill = phase === "waiting" && waitingSince.current !== null ? now - waitingSince.current : waitedMs;
  const reasons = reasonsOf(lastAnswer);

  return (
    <article className="robot" data-testid="robot-view">
      <div className="robot-head">
        <div>
          <h1>Layout robot</h1>
          <p className="muted small">
            A simulated robot chalks the project's partitions on the slab and asks Aurora before every
            unit. When a unit is held it skips it and comes back once the site changes.
          </p>
          <p className="muted small">
            <Link to="/site" data-testid="robot-site-link">See this robot on the site view</Link>
          </p>
        </div>
        <div className="row">
          <Badge tone="accent" testId="robot-badge">
            Simulated robot
          </Badge>
          <span className={`robot-state robot-state-${statusState}`} data-testid="robot-status" data-state={statusState}>
            {statusText}
          </span>
        </div>
      </div>

      <div className="row"><button className="button" disabled={busy || phase === "asking"} onClick={() => void prepareWork()}>{planning ? "Aurora is planning the layout work…" : "Prepare robot work"}</button><span className="muted small">Adds planned layout tasks for assigned rooms. Existing work and start checks are preserved.</span></div>
      {phase === "ready" && <div className="panel"><p>The registered robot will load this drawing and ask Aurora before marking each room. No movement has started.</p><button className="button button-primary" disabled={busy || units.length === 0} onClick={() => void startLayout()}>{busy ? planning ? "Waiting for the programme…" : "Confirming drawing…" : "Load drawing & start robot"}</button>{units.length === 0 && <p>No assigned partition work is available on this floor. Choose another floor.</p>}</div>}
      <div className="robot-grid">
        <section className="robot-stage" aria-labelledby="robot-stage-heading">
          <h2 id="robot-stage-heading" className="robot-stage-heading">
            {setup.after.sheet}, drawing layout
          </h2>
          {webgl && !fallback ? (
            <Immersive title={`${setup.after.sheet}, Rev ${geometry.revision} · ${statusText}`} testId="robot"><div
              className="robot-3d"
              data-testid="robot-3d"
              ref={host}
              role="img"
              aria-label={`${setup.after.sheet} in 3D with the chalked partitions and the robot. Drag to rotate, scroll to zoom.`}
            /></Immersive>
          ) : (
            <div className="robot-fallback" data-testid="robot-fallback">
              <p>
                This browser has no WebGL, so the slab stays flat. The list and the checks show what the robot asked
                and what it was told.
              </p>
            </div>
          )}
          <div className="robot-stage-foot">
            <p className="small" data-testid="robot-revision" data-revision={geometry.revision}>
              Working from <strong>Rev {geometry.revision}</strong>
              {switched && <span className="robot-switched"> · {switched}</span>}
            </p>
            {load?.notice && load.confirmation && (
              <p className="small muted" data-testid="robot-notice" data-status={load.confirmation.status}>
                Aurora told it about {load.notice.sheet} Rev {load.notice.revision} at {formatTime(load.notice.sent_at)}
                ; it loaded the revision and confirmed it at {formatTime(load.confirmation.confirmed_at)}.
              </p>
            )}
            <p className="small muted" data-testid="robot-marked">
              Chalked lines: {marked.length === 0 ? "none yet" : marked.join(", ")}
            </p>
            <p className="robot-hint small muted">Drag to rotate, scroll to zoom</p>
          </div>
        </section>

        <aside className="robot-side">
          <section className="panel robot-card" data-testid="robot-worklist">
            <div className="panel-head">
              <h2>Work list</h2>
              <span className="panel-aside">
                {chalkedUnits.length} of {units.length} chalked
              </span>
            </div>
            <ol className="robot-worklist">
              {units.map((unit, position) => {
                const outcome = outcomes[unit.name] ?? "todo";
                return (
                  <li key={unit.name} data-testid="robot-unit" data-unit={unit.name} data-state={outcome}>
                    <span className="num robot-unit-order">{position + 1}</span>
                    <span>Unit {unit.name}</span>
                    <span className={`robot-unit-state robot-unit-${outcome}`}>{outcomeLabel(outcome)}</span>
                  </li>
                );
              })}
            </ol>
            <p className="muted small" data-testid="robot-standstill">
              Stood still {standStill(stoodStill)}.
            </p>
          </section>

          {waitingUnits.length > 0 && (
            <section className="panel robot-card" data-testid="robot-skipped">
              <div className="panel-head">
                <h2>Skipped, waiting</h2>
                <span className="panel-aside">{waitingUnits.length}</span>
              </div>
              <ul className="robot-skipped-list">
                {waitingUnits.map((unit) => {
                  const answer = answers[unit.name];
                  const reason = answer?.reasons?.[0];
                  return (
                    <li key={unit.name} data-testid="robot-skipped-unit" data-unit={unit.name}>
                      <p>
                        <strong>Unit {unit.name}</strong>: {answer?.summary ?? "The start check could not be answered."}
                      </p>
                      {reason && <p className="small">{reason.text}</p>}
                      {reason &&
                        sourcesOf(reason).map((source) => (
                          <a
                            className="robot-source small"
                            data-testid="robot-source"
                            key={`${source.eventId}-${source.quote}`}
                            href={projectApiUrl(`/api/events/${encodeURIComponent(source.eventId)}`)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span className="num">{source.eventId}</span>: "{source.quote}"
                          </a>
                        ))}
                      <p className="muted small">Asks again when the flags or the waiting list change.</p>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          <section className="panel robot-card" aria-labelledby="robot-answer-heading">
            <div className="panel-head">
              <h2 id="robot-answer-heading">Last answer</h2>
              <span className="panel-aside">{request ? `asked for ${request.unit}` : "not asked yet"}</span>
            </div>
            {failure ? (
              <p className="robot-failure" role="alert">
                The robot could not continue: {failure} No work was started from this failed request.
              </p>
            ) : !lastAnswer ? (
              <p className="muted">The robot has not asked yet.</p>
            ) : (
              <>
                <p className="robot-summary" data-testid="robot-summary">
                  {lastAnswer.summary}
                </p>
                {reasons.length === 0 ? (
                  <p className="muted">No reason stands in the way.</p>
                ) : (
                  <ul className="robot-reasons">
                    {reasons.map((reason) => (
                      <li
                        className="robot-reason"
                        data-testid="robot-reason"
                        data-kind={reason.kind}
                        key={`${reason.kind}-${reason.text}`}
                      >
                        <div className="row">
                          <Badge tone={reason.blocking ? "danger" : "warning"}>{reason.kind.replace(/_/g, " ")}</Badge>
                          <span className="small muted">{reason.blocking ? "blocking" : "not blocking"}</span>
                        </div>
                        <p>{reason.text}</p>
                        {sourcesOf(reason).map((source) => (
                          <a
                            className="robot-source small"
                            data-testid="robot-source"
                            key={`${source.eventId}-${source.quote}`}
                            href={projectApiUrl(`/api/events/${encodeURIComponent(source.eventId)}`)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span className="num">{source.eventId}</span>: "{source.quote}"
                          </a>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>

          <section className="panel robot-card" aria-labelledby="robot-log-heading">
            <div className="panel-head">
              <h2 id="robot-log-heading">Checks</h2>
              <span className="panel-aside">{log.length === 1 ? "1 check" : `${log.length} checks`}</span>
            </div>
            <ol className="robot-log" data-testid="robot-log">
              {log.length === 0 && <li className="muted">No check yet.</li>}
              {log.map((entry, position) => (
                <li key={`${entry.unit}-${position}`} data-testid="robot-log-entry" data-allowed={entry.allowed}>
                  <span className="num robot-log-time">{formatTime(entry.at)}</span>
                  <span>Unit {entry.unit}</span>
                  <span className={`robot-log-allowed robot-log-${entry.allowed}`}>{entry.allowed}</span>
                </li>
              ))}
            </ol>
          </section>

          <section className="panel robot-card" aria-labelledby="robot-json-heading">
            <h2 id="robot-json-heading">Last request and answer</h2>
            <pre className="robot-json" data-testid="robot-json">
              {request && lastAnswer ? JSON.stringify({ request, answer: lastAnswer }, null, 2) : "The robot has not asked yet."}
            </pre>
          </section>

          {stepMode && (
            <button type="button" className="button" data-testid="robot-step" disabled={!loaded || busy || phase !== "asking"} onClick={step}>
              Step one unit
            </button>
          )}
          <p className="muted small">The robot only asks. It never decides, holds or releases work.</p>
        </aside>
      </div>
    </article>
  );
}

function outcomeLabel(outcome: Outcome | "todo") {
  if (outcome === "chalked") return "chalked";
  if (outcome === "waiting") return "waiting";
  if (outcome === "error") return "check failed";
  return "next";
}

function standStill(ms: number) {
  if (ms < 1000) return "less than a second";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${seconds % 60} s`;
}
