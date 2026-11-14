import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Flag,
  type Plan,
  type Project,
  type Readiness,
  type StartCheck,
  type WaitingItem,
} from "../../api/client";
import { useQuery } from "../../api/useQuery";
import type { Geometry } from "../../components/plan3d/geometry";
import { loadProjectGeometry } from "../drawings/api";
import { webglAvailable } from "../../components/plan3d/scene";
import { STATE_LABELS, buildSite, type SiteState, type SiteUnit } from "../../components/site3d/units";
import { createSiteScene, type SiteScene } from "../../components/site3d/siteScene";

/** How many units the caption names: a still, not a second unit list. */
const MAX_ROWS = 6;
const WAITING_STATES: SiteState[] = ["inspection", "confirmation", "unknown"];

function siteHref(unit: string): string {
  return `/site?unit=${encodeURIComponent(unit)}`;
}

interface StillInput {
  project: Project;
  readiness: Readiness;
  checks: StartCheck[];
  geometry: Geometry | null;
}

/** The inputs the site page builds its model from, minus the flag, plan and waiting lists the Today page holds. */
async function loadStill(): Promise<StillInput> {
  const [project, readiness, checks, geometry] = await Promise.all([
    api.project(),
    api.readiness(),
    api.checks(),
    loadProjectGeometry(),
  ]);
  return { project, readiness, checks, geometry };
}

function Named({ unit }: { unit: SiteUnit }) {
  return (
    <li
      className={`ov-site-unit ov-site-unit-${unit.state}`}
      data-testid="overview-site-unit"
      data-unit={unit.unit}
      data-state={unit.state}
    >
      <Link to={siteHref(unit.unit)}>{unit.unit}</Link>
      <span className="ov-site-word">{STATE_LABELS[unit.state]}</span>
      {unit.heldBy && (
        <span className="muted small" title={unit.heldBy}>
          {unit.heldBy}
        </span>
      )}
    </li>
  );
}

/**
 * A still of the site on the Today page: one render of the scene the site page draws, so the building and every
 * unit are in the state the record gives them without a second copy of the scene code. A click opens the site
 * view on the unit the still is about, and without WebGL the same units are named in a short list.
 */
export function SiteStill({ flags, waiting, plan }: { flags: Flag[]; waiting: WaitingItem[]; plan: Plan }) {
  const still = useQuery(loadStill, []);
  const [canvas] = useState(() => webglAvailable());
  const [failed, setFailed] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<SiteScene | null>(null);
  const drawn = useRef<string | null>(null);

  const model = useMemo(
    () => (still.data ? buildSite({ ...still.data, flags, waiting, plan }) : null),
    [still.data, flags, waiting, plan],
  );

  const held = model?.units.filter((unit) => unit.heldBy) ?? [];
  const waitingUnits = model?.units.filter((unit) => !unit.heldBy && WAITING_STATES.includes(unit.state)) ?? [];
  const named = [...held, ...waitingUnits];
  const focus = named[0] ?? model?.units.find((unit) => unit.state === "working") ?? model?.units[0] ?? null;
  const shown3d = canvas && !failed;
  const shown = named.slice(0, MAX_ROWS);
  // Only the drawing and the state of every unit change the picture: the page polls, so a rebuild every
  // three seconds would be an animation loop by accident.
  const signature = model
    ? `${still.data?.geometry?.revision ?? "-"}|${focus?.unit ?? "-"}|${model.units
        .map((unit) => `${unit.unit}:${unit.state}:${unit.stage}:${unit.heldBy ?? ""}`)
        .join(",")}`
    : "";

  useEffect(() => {
    const element = host.current;
    if (!shown3d || !element || !model || !focus) return;
    if (!scene.current) {
      try {
        // A still: the shared scene with orbit and pointer selection off, so it renders once and stays still.
        scene.current = createSiteScene(element, () => undefined, () => undefined, { interactive: false });
      } catch {
        setFailed(true);
        return;
      }
      drawn.current = null;
    }
    if (drawn.current === signature) return;
    scene.current.update(model, still.data?.geometry ?? null, focus.unit);
    drawn.current = signature;
  }, [shown3d, model, focus, signature, still.data?.geometry]);

  useEffect(() => () => {
    scene.current?.dispose();
    scene.current = null;
  }, []);

  if (still.error) {
    return (
      <section className="panel ov-site" data-testid="overview-site" data-webgl="no">
        <div className="panel-head">
          <h2>On site</h2>
        </div>
        <p className="muted small" data-testid="overview-site-fallback">
          The site could not be loaded. {still.error}
        </p>
        <button type="button" className="button" onClick={still.reload}>
          Retry
        </button>
      </section>
    );
  }
  if (!model || !focus) return null;

  return (
    <section
      className="panel ov-site"
      data-testid="overview-site"
      data-units={model.units.length}
      data-webgl={shown3d ? "yes" : "no"}
    >
      <div className="panel-head">
        <h2>On site</h2>
        <span className="panel-aside">{model.units.length} units</span>
      </div>

      {shown3d ? (
        <Link
          className="ov-site-still"
          to={siteHref(focus.unit)}
          data-testid="overview-site-link"
          data-unit={focus.unit}
          title={`Open the site view on unit ${focus.unit}`}
        >
          <div
            className="ov-site-canvas"
            ref={host}
            role="img"
            aria-label={`${model.name} in 3D: one plate per floor, every unit in the colour of its state. Opens the site view on unit ${focus.unit}.`}
          />
        </Link>
      ) : (
        <>
          <p className="muted small" data-testid="overview-site-fallback">
            This browser has no WebGL, so the site is a short list of the units the record holds or waits on.
          </p>
          {shown.length === 0 && (
            <p className="small">
              <Link to={siteHref(focus.unit)} data-testid="overview-site-link" data-unit={focus.unit}>
                Open the site view on unit {focus.unit}
              </Link>
            </p>
          )}
        </>
      )}

      <ul className="ov-site-units" data-testid="overview-site-units">
        {shown.map((unit) => (
          <Named key={unit.unit} unit={unit} />
        ))}
      </ul>
    </section>
  );
}
