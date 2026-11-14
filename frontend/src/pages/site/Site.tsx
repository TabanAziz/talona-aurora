import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type RecordEntry, type Machine } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { loadProjectGeometry } from "../drawings/api";
import { webglAvailable } from "../../components/plan3d/scene";
import { Empty, ErrorState, Loading } from "../../components/States";
import { STAGE_LABELS, STATE_LABELS, buildSite, type SiteInput, type SiteModel } from "./units";
import { createSiteScene, type SiteScene } from "./siteScene";
import { SitePlay } from "../siteplay/SitePlay";
import { SiteAsk } from "../siteask/SiteAsk";
import { actorsFor } from "../sitescene/actors";
import { actorLayer } from "../sitescene/layer";
import { SiteActors, SiteStops } from "../sitescene/SiteActors";
import { Immersive } from "../../components/immersive/Immersive";
import "./site.css";


type SiteData = SiteInput & {record: RecordEntry[]; machines: Machine[]};
async function loadSite(): Promise<SiteData | null> {
  const [project, plan, flags, waiting, readiness, checks, geometry, record, machines] = await Promise.all([
    api.project(),
    api.plan(),
    api.flags(),
    api.waiting(),
    api.readiness(),
    api.checks(),
    loadProjectGeometry(),
    api.record(),
    api.machines(),
  ]);
  return { project, plan, flags, waiting, readiness, checks, geometry, record, machines };
}

export function Site() {
  const forced = useForcedState();
  const site = useQuery(loadSite, []);
  if (forced === "empty") return <Empty>The project has no units to show on site.</Empty>;
  if (site.error) return <ErrorState message={site.error} onRetry={site.reload} />;
  if (site.loading || site.data === undefined) return <Loading rows={6} />;
  if (site.data === null || site.data.project.units.length === 0) {
    return <Empty>The project has no units to show on site.</Empty>;
  }
  return <SiteBody input={site.data} onReload={site.reload} />;
}

function SiteBody({ input, onReload }: { input: SiteData; onReload: () => void }) {
  const model = useMemo(() => buildSite(input), [input]);
  const actors = useMemo(() => actorsFor({...input,day:model.day,units:input.project.units}),[input,model.day]);
  const actorRef = useRef(actors);
  actorRef.current = actors;
  const layer = useMemo(()=>actorLayer(()=>actorRef.current),[]);
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(() => {
    // A link may name the unit, so a printed sheet or a browser check can open one unit directly.
    const named = new URLSearchParams(window.location.search).get("unit");
    return named && input.project.units.includes(named) ? named : null;
  });
  const [webgl] = useState(() => webglAvailable());
  const [fallback, setFallback] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<SiteScene | null>(null);

  const select = useCallback((unit: string) => setSelected(unit), []);

  useEffect(() => {
    const element = host.current;
    if (!webgl || !element) return;
    try {
      scene.current = createSiteScene(element, select, (href) => navigate(href), {layer});
    } catch {
      scene.current = null;
      setFallback(true);
      return;
    }
    return () => {
      scene.current?.dispose();
      scene.current = null;
    };
  }, [webgl, navigate, select, layer]);

  useEffect(() => {
    scene.current?.update(model, input.geometry, selected);
  }, [model, input.geometry, selected]);

  const unit = model.units.find((item) => item.unit === selected) ?? null;
  const counts = new Map<string, number>();
  for (const item of model.units) counts.set(item.state, (counts.get(item.state) ?? 0) + 1);

  return (
    <article className="site" data-testid="site-view">
      <header className="page-head">
        <div>
          <h1>{model.name} site</h1>
          <p className="muted small">
            Every room and area in its construction stage and its state from the record. Available drawing geometry
            is shown on its floor. Areas without drawing coordinates are marked schematic.
          </p>
        </div>
        <div className="row">
          <span className="muted small num">{model.day}</span>
        </div>
      </header>

      <div className="site-grid">
        <section className="site-stage" aria-label={`${model.name} in 3D`}>
          {webgl && !fallback ? (
            <Immersive title={`${model.name} site`} testId="site"><div className="sitescene-composition"><div
              className="site-3d"
              data-testid="site-3d"
              ref={host}
              role="img"
              aria-label={`${model.name}: the site in 3D with one plate per floor, every unit in its construction stage and its state. Drag to rotate, scroll to zoom, click a unit for its open points.`}
            /><SiteStops actors={actors} /></div></Immersive>
          ) : (
            <div className="site-fallback" data-testid="site-fallback">
              <p>
                This browser has no WebGL, so the site is shown as a list. Every unit, its stage, its state and its
                open points are the same as in the 3D view.
              </p>
            </div>
          )}
          <ul className="site-units" aria-label="Units on site">
            {model.units.map((item) => (
              <li key={item.unit}>
                <button
                  type="button"
                  className={`site-unit site-unit-${item.state}${selected === item.unit ? " site-unit-selected" : ""}`}
                  data-testid="site-unit"
                  data-unit={item.unit}
                  data-state={item.state}
                  data-stage={item.stage}
                  data-level={item.level}
                  aria-pressed={selected === item.unit}
                  onClick={() => setSelected(selected === item.unit ? null : item.unit)}
                >
                  <span className="site-unit-name">{item.unit}</span>
                  <span className="site-unit-state">{STATE_LABELS[item.state]}</span>
                  <span className="site-unit-stage">{STAGE_LABELS[item.stage]}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="muted small">Drag to rotate, scroll to zoom. Click a unit for its open points.</p>
          <SiteActors actors={actors} />
        </section>

        <aside className="site-side">
          <SitePlay onChanged={onReload} />
          <section className="panel site-card" aria-labelledby="site-legend-heading">
            <h2 id="site-legend-heading">Legend</h2>
            <ul className="site-legend" data-testid="site-legend">
              {(Object.keys(STATE_LABELS) as (keyof typeof STATE_LABELS)[])
                .filter((state) => state !== "unknown" || (counts.get(state) ?? 0) > 0)
                .map((state) => (
                  <li key={state} className={`site-legend-item site-legend-${state}`}>
                    <span className="site-swatch" aria-hidden="true" />
                    <span>{STATE_LABELS[state]}</span>
                    <span className="num muted">{counts.get(state)}</span>
                  </li>
                ))}
            </ul>
            <p className="muted small">
              Each unit is drawn in the stage of its next open task: a bare slab is not started, stud lines are
              framing, low open walls are rough-in, and solid walls are closed.
            </p>
          </section>

          {unit ? (
            <section className="panel site-card" aria-labelledby="site-unit-heading" data-testid="site-selected" data-unit={unit.unit}>
              <div className="panel-head">
                <h2 id="site-unit-heading">Unit {unit.unit}</h2>
                <button type="button" className="site-clear" onClick={() => setSelected(null)}>Clear selection</button>
              </div>
              <p className="small">
                <Badge>{STAGE_LABELS[unit.stage]}</Badge> <span className={`site-state site-state-${unit.state}`}>{STATE_LABELS[unit.state]}</span>
                {unit.schematic && <span className="muted"> · schematic floor</span>}
              </p>
              {unit.heldBy && <p className="site-held" data-testid="site-held">Held: {unit.heldBy}</p>}
              <h3>Open points</h3>
              {unit.points.length === 0 ? (
                <p className="muted">Nothing open on this unit.</p>
              ) : (
                <ul className="site-points" data-testid="site-points">
                  {unit.points.map((point) => (
                    <li key={`${point.kind}-${point.id}`} className="site-point" data-testid="site-point" data-kind={point.kind}>
                      <span className="site-point-kind">{point.kind}</span>
                      <Link to={point.href} className="site-point-link">{point.label}</Link>
                      <span className="muted small">{point.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : (
            <section className="panel site-card" aria-labelledby="site-people-heading">
              <h2 id="site-people-heading">On site today</h2>
              <p className="muted small">Select a unit on the model or in the list to see its open points.</p>
              <People title="Crews" figures={model.crews} empty="No crew has work in a unit today." />
              <People title="Machines" figures={model.machines} empty="No machine has asked Aurora yet." />
            </section>
          )}

          {unit && (
            <>
              <People title="Crews" figures={model.crews} empty="No crew has work in a unit today." />
              <People title="Machines" figures={model.machines} empty="No machine has asked Aurora yet." />
            </>
          )}

          <SiteAsk unit={unit} stored={input.checks} />
        </aside>
      </div>
    </article>
  );
}

function People({ title, figures, empty }: { title: string; figures: SiteModel["crews"]; empty: string }) {
  return (
    <section className="site-people">
      <h3>{title}</h3>
      {figures.length === 0 ? (
        <p className="muted small">{empty}</p>
      ) : (
        <ul className="site-figures" data-testid={title === "Crews" ? "site-crews" : "site-machines"}>
          {figures.map((figure) => (
            <li key={figure.id} data-testid={title === "Crews" ? "site-crew" : "site-machine"}>
              <Link to={figure.href} className="site-figure-link">{figure.label}</Link>{" "}
              <span className="muted small">in {figure.unit}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
