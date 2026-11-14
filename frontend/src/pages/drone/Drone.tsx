import { projectApiUrl } from "../../api/workspace";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StartCheck } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { Empty, ErrorState, Loading } from "../../components/States";
import { loadGeometry, type Geometry } from "../../components/plan3d/geometry";
import { webglAvailable } from "../../components/plan3d/scene";
import { buildSite, type SiteInput } from "../../components/site3d/units";
import type { SiteScene } from "../../components/site3d/siteScene";
import { DRONE, droneApi, type Machine, type MachineReportResult } from "./api";
import { createDroneScene, type FlightView } from "./droneScene";
import { surveyWalls, wallReport, type SurveyWall } from "./survey";
import { Immersive } from "../../components/immersive/Immersive";
import { drawingsApi } from "../drawings/api";
import "./drone.css";

interface Setup { input: SiteInput; before: Geometry; after: Geometry; machine: Machine; hasHistory: boolean }
interface Observation { wall: SurveyWall; result: MachineReportResult }
type Phase = "ready" | "checking" | "flying" | "stopped" | "done" | "error";

async function loadSetup(): Promise<Setup | null> {
  const [project, plan, flags, waiting, readiness, checks, diffs, machines] = await Promise.all([
    api.project(), api.plan(), api.flags(), api.waiting(), api.readiness(), api.checks(), api.diffs(), droneApi.machines(),
  ]);
  const machine = machines.find((item) => item.id === DRONE && item.kind === "drone") ?? machines.find(item => item.kind === "drone");
  const diff = diffs.filter((item) => (machine?.sheets ?? []).includes(item.sheet) && item.before_geometry_url && item.after_geometry_url)
    .sort((a, b) => b.to_rev.localeCompare(a.to_rev))[0];
  if (!machine) return null;
  if (!diff?.before_geometry_url || !diff.after_geometry_url) {
    const register = await drawingsApi.list();
    for (const sheet of register.sheets.filter(sheet => (machine.sheets ?? []).includes(sheet.id))) {
      const revision = sheet.revisions.find(revision => revision.revision === sheet.current_revision);
      if (!revision?.geometry_url) continue;
      const geometry = await loadGeometry(revision.geometry_url);
      return { input: { project, plan, flags, waiting, readiness, checks, geometry }, before: geometry, after: geometry, machine, hasHistory: false };
    }
    return null;
  }
  const [before, after] = await Promise.all([loadGeometry(diff.before_geometry_url), loadGeometry(diff.after_geometry_url)]);
  return { input: { project, plan, flags, waiting, readiness, checks, geometry: after }, before, after, machine, hasHistory: true };
}

export function Drone() {
  const forced = useForcedState();
  const setup = useQuery(loadSetup, []);
  if (forced === "empty") return <Empty>No registered survey drone has a changed sheet with geometry.</Empty>;
  if (setup.error) return <ErrorState message={setup.error} onRetry={setup.reload} />;
  if (setup.loading || setup.data === undefined) return <Loading rows={6} />;
  if (!setup.data) return <Empty>No registered survey drone has a changed sheet with geometry. Open Machines to check its registration.</Empty>;
  return <DroneBody setup={setup.data} />;
}

function DroneBody({ setup }: { setup: Setup }) {
  const [position, setPosition] = useState<"before" | "after">(setup.hasHistory ? "before" : "after");
  const [phase, setPhase] = useState<Phase>("ready");
  const [checks, setChecks] = useState<StartCheck[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [activeWall, setActiveWall] = useState<SurveyWall | null>(null);
  const [fallback, setFallback] = useState(() => !webglAvailable());
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<SiteScene | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  const measured = position === "before" ? setup.before : setup.after;
  const walls = useMemo(() => surveyWalls(setup.after, measured, setup.machine), [setup.after, measured, setup.machine]);
  const model = useMemo(() => buildSite(setup.input), [setup.input]);
  const flight = useRef<FlightView>({ flying: false, stopped: false, wall: null });
  flight.current = { flying: phase === "flying", stopped: phase === "stopped" || phase === "error", wall: activeWall };
  const running = phase === "checking" || phase === "flying" || confirming;
  const raised = [...new Map(observations.flatMap((item) => item.result.flags ?? []).map((flag) => [flag.id, flag])).values()];
  const status = { ready: "Ready on the ground", checking: "Checking before flight", flying: "Survey in progress", stopped: "Flight stopped", done: "Survey complete", error: "Survey stopped" }[phase];

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (fallback || !host.current) return;
    try { scene.current = createDroneScene(host.current, () => flight.current); }
    catch { setFallback(true); }
    return () => { scene.current?.dispose(); scene.current = null; };
  }, [fallback]);
  useEffect(() => { scene.current?.update(model, measured, activeWall?.unit ?? null); }, [model, measured, phase, activeWall]);

  async function confirm() {
    if (busy.current) return;
    busy.current = true;
    setConfirming(true);
    setFailure(null);
    try {
      const response = await droneApi.confirm(setup.after.sheet, setup.after.revision, setup.machine.id);
      setConfirmation(response.status === "confirmed" ? `Loaded ${response.sheet} Rev ${response.revision}. Confirmation recorded.` : `Rev ${response.current_revision} is now current. Reload the page before flying.`);
    } catch (error) { setFailure(error instanceof Error ? error.message : "The revision could not be confirmed."); }
    finally { busy.current = false; setConfirming(false); }
  }

  async function scan() {
    if (busy.current || walls.length === 0) return;
    busy.current = true;
    setPhase("checking"); setFailure(null); setChecks([]); setObservations([]); setActiveWall(null);
    try {
      const answers: StartCheck[] = [];
      for (const unit of [...new Set(walls.map((item) => item.unit))]) {
        const check = await api.canStart({ asked_by: setup.machine.id, unit, activity: "survey walls" });
        if (!mounted.current) return;
        answers.push(check); setChecks([...answers]);
        if (check.allowed !== "yes" || (check.reasons ?? []).some((reason) => reason.blocking)) {
          setPhase("stopped"); return;
        }
      }
      const flightId = `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
      setPhase("flying");
      for (const wall of walls) {
        if (!mounted.current) return;
        setActiveWall(wall);
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        if (!mounted.current) return;
        const result = await droneApi.report(wallReport(wall, measured.sheet, flightId, new Date().toISOString()), setup.machine.id);
        if (!mounted.current) return;
        setObservations((previous) => [...previous, { wall, result }]);
        if (result.status !== "understood") throw new Error(result.reason ?? "Aurora could not read this measured wall. The survey stopped.");
      }
      setActiveWall(null); setPhase("done");
    } catch (error) {
      if (mounted.current) { setFailure(error instanceof Error ? error.message : "The survey could not finish."); setActiveWall(null); setPhase("error"); }
    } finally { busy.current = false; }
  }

  return <article className="drone" data-testid="drone-view" data-phase={phase}>
    <header className="page-head">
      <div><h1>Survey drone, level 3</h1><p className="muted">Measured wall positions go to Aurora. The superintendent reviews any difference.</p></div>
      <div className="row"><Badge tone="accent" testId="drone-badge">Simulated drone</Badge></div>
    </header>
    <div className="drone-grid">
      <section className="drone-stage" aria-label="Survey scene">
        <div className="drone-stage-title"><h2>{setup.after.sheet}, level 3</h2><span className="muted">{setup.machine.name}</span></div>
        {!fallback ? <Immersive title={`${setup.after.sheet}, level 3 survey`} testId="drone"><div ref={host} className="drone-3d" data-testid="drone-3d" role="img" aria-label="Maple Court site with a simulated survey drone. Drag to rotate, scroll to zoom." /></Immersive> :
          <div className="drone-fallback" data-testid="drone-fallback"><p>3D is unavailable in this browser. The wall list and recorded answers show the same survey.</p></div>}
        <p className={`drone-status drone-status-${phase}`} data-testid="drone-status" aria-live="polite">{status}{activeWall ? `: ${activeWall.wall.id}, unit ${activeWall.unit}` : ""}</p>
        <p className="small muted">Registered area: {(setup.machine.units ?? []).join(", ")}. Other units stay outside this flight. The rest of the building is schematic.</p>
        <p className="small muted">Drag to rotate, scroll to zoom. The drone stays on the ground until Aurora answers yes.</p>
      </section>
      <aside className="drone-side">
        <section className="panel drone-card" aria-labelledby="drone-flight-heading">
          <h2 id="drone-flight-heading">Prepare a survey</h2>
          <p className="small muted">{setup.hasHistory ? "Synthetic measurements demonstrate an old wall position and the current one. The loaded drawing stays current." : "This project has one drawing revision. Simulated measurements use its current wall positions; no earlier revision is invented."}</p>
          <button className="button" type="button" data-testid="drone-confirm" disabled={running} onClick={() => void confirm()}>{confirming ? "Confirming revision…" : `Load and confirm Rev ${setup.after.revision}`}</button>
          {confirmation && <p className="small" data-testid="drone-confirmation">{confirmation}</p>}
          <label className="drone-choice" htmlFor="drone-position">Observed wall positions
            <select id="drone-position" data-testid="drone-position" value={position} disabled={running} onChange={(event) => { setPosition(event.target.value as "before" | "after"); setPhase("ready"); setObservations([]); setChecks([]); setFailure(null); }}>
              {setup.hasHistory && <option value="before">Rev {setup.before.revision} position (old)</option>}<option value="after">Rev {setup.after.revision} position (current)</option>
            </select>
          </label>
          <button className="button button-primary" type="button" data-testid="drone-scan" disabled={running || walls.length === 0} onClick={() => void scan()}>{running ? "Survey in progress…" : "Ask Aurora and scan"}</button>
          {walls.length === 0 && <p>No walls of this sheet fall within the drone's registered area.</p>}
          <p className="small muted">{setup.machine.name} only asks, confirms and reports. It never decides, holds or releases work.</p>
        </section>
        {(checks.length > 0 || failure) && <section className="panel drone-card" aria-labelledby="drone-check-heading">
          <h2 id="drone-check-heading">Before flight</h2>
          {failure && <p className="drone-failure" role="alert">{failure} Retry the survey once the connection is available.</p>}
          {checks.map((check) => <div className="drone-check" data-testid="drone-check" data-allowed={check.allowed} key={check.id}>
            <p><Badge tone={check.allowed === "yes" ? "success" : "danger"}>{check.allowed === "yes" ? "Cleared" : "Not cleared"}</Badge> Unit {check.unit}</p>
            <p>{check.summary}</p>
            {(check.reasons ?? []).map((reason, index) => <div key={`${reason.kind}-${index}`}><p className="small">{reason.text}</p>{(reason.sources ?? []).map((source) => <a className="drone-source small" key={`${source.event_id}-${source.quote}`} href={projectApiUrl(`/api/events/${encodeURIComponent(source.event_id)}`)} target="_blank" rel="noreferrer">{source.quote}</a>)}</div>)}
            {check.allowed !== "yes" && <p className="small drone-failure">No flight or wall report was started. Ask again after the site changes.</p>}
          </div>)}
        </section>}
      </aside>
    </div>
    <section className="panel drone-card" aria-labelledby="drone-walls-heading">
      <div className="panel-head"><h2 id="drone-walls-heading">Wall observations</h2><span className="muted">{observations.length} of {walls.length} reported</span></div>
      {observations.length === 0 ? <p className="muted">No measurements sent. Choose a position and ask Aurora to start the survey.</p> : <ul className="drone-reports">
        {observations.map(({ wall, result }) => <li key={result.report_id} data-testid="drone-report" data-wall={wall.wall.id} data-revision={result.matches_revision ?? "none"}>
          <strong>{wall.wall.id}, unit {wall.unit}</strong><span>Matches {result.matches_revision ? `Rev ${result.matches_revision}` : "no revision on record"}</span>
          <span>{(result.flags ?? []).length > 0 ? "Difference flagged" : result.status === "understood" ? "Recorded, no new flag" : result.reason}</span>
          <a className="small" href={projectApiUrl(`/api/events/${encodeURIComponent(result.event_id)}`)} target="_blank" rel="noreferrer">Open measured report</a>
        </li>)}
      </ul>}
      {phase === "done" && raised.length === 0 && <p className="drone-success" data-testid="drone-clear">Survey complete. These measurements raised no new flags.</p>}
    </section>
    {raised.map((flag) => <section className="panel drone-card" key={flag.id} data-testid="drone-flag">
      <h2><Link to={`/flags/${encodeURIComponent(flag.id)}`}>{flag.title}</Link></h2><p>{flag.summary}</p>
      <div className="drone-evidence">{(flag.evidence ?? []).map((source) => <blockquote key={`${source.event_id}-${source.quote}`} data-testid="drone-evidence"><p>{source.quote}</p><a className="small" href={projectApiUrl(`/api/events/${encodeURIComponent(source.event_id)}`)} target="_blank" rel="noreferrer">{source.sender}, {source.channel}</a></blockquote>)}</div>
      <p className="small muted">The drone has reported the difference. <Link to={`/flags/${encodeURIComponent(flag.id)}`}>The superintendent decides on this flag.</Link></p>
    </section>)}
    <p className="small"><Link to="/machines">All machines</Link> · <Link to="/site">Site view</Link></p>
  </article>;
}
