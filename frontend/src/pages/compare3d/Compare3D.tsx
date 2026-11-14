import { useEffect, useMemo, useRef, useState } from "react";
import { api, type DrawingDiff } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { Async } from "../../components/States";
import { loadGeometry, type Geometry } from "../../components/plan3d/geometry";
import { createViewer, type Layer, type ScreenPoint, type ScreenPoints, type Viewer } from "../../components/plan3d/scene";
import { ViewerControls } from "../../components/plan3d/ViewerControls";
import {
  affectedTasks,
  primaryCallout,
  secondaryCallouts,
  taskMeta,
  unitRows,
  unitsOf,
  type Callout,
} from "./floorStack";
import { splitFloors as floorsOf } from "../../components/plan3d/floors";
import "./compare3d.css";

/** The callout column: plaques are as wide as this and stacked from the top, so they never overlap. */
const PLAQUE_WIDTH = 216;
const PLAQUE_STEP = 92;
const PLAQUE_TOP = 12;
const EDGE = 12;
/** Below this host width the plaques move under the stack as a plain list. */
const COLUMN_FROM = 720;

interface Props {
  diff: DrawingDiff;
  layer: Layer;
  /** Called when the browser refuses to start WebGL, so the page can fall back to the 2D drawing. */
  onUnavailable: () => void;
}

export function Compare3D({ diff, layer, onUnavailable }: Props) {
  const before = diff.before_geometry_url ?? "";
  const after = diff.after_geometry_url ?? "";
  const geometry = useQuery(() => Promise.all([loadGeometry(before), loadGeometry(after)]), [before, after], {
    skip: !before || !after,
  });
  const plan = useQuery(() => api.plan(), []);

  return (
    <Async query={geometry} rows={6}>
      {([from, to]) => (
        <Scene
          diff={diff}
          before={from}
          after={to}
          layer={layer}
          onUnavailable={onUnavailable}
          plan={plan.data}
        />
      )}
    </Async>
  );
}

interface SceneProps extends Props {
  before: Geometry;
  after: Geometry;
  plan: Awaited<ReturnType<typeof api.plan>> | undefined;
}

function Scene({ diff, before, after, layer, onUnavailable, plan }: SceneProps) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const layerRef = useRef(layer);
  layerRef.current = layer;
  const [points, setPoints] = useState<ScreenPoints | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  const units = useMemo(() => unitsOf(diff, after), [diff, after]);
  const tasks = useMemo(() => affectedTasks(plan, units), [plan, units]);
  const callouts = useMemo<Callout[]>(
    () => [primaryCallout(diff), ...secondaryCallouts(tasks, after.rooms ?? [])],
    [diff, tasks, after],
  );
  const floors = useMemo(() => floorsOf(after), [after]);
  const directory = useMemo(() => unitRows(units, tasks), [units, tasks]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    try {
      viewer.current = createViewer(
        element,
        before,
        after,
        () => {
          const next = viewer.current?.points() ?? null;
          setPoints(next);
          const box = { width: element.clientWidth, height: element.clientHeight };
          setSize((current) =>
            current.width === box.width && current.height === box.height ? current : box,
          );
        },
        floors,
      );
      viewer.current.show(layerRef.current);
    } catch {
      viewer.current = null;
      onUnavailable();
      return;
    }
    return () => {
      viewer.current?.dispose();
      viewer.current = null;
    };
    // The viewer is rebuilt only for new geometry: a layer change keeps the camera where the user put it.
  }, [before, after, floors]);

  useEffect(() => {
    viewer.current?.show(layer);
  }, [layer]);

  const column = size.width >= COLUMN_FROM && layer === "overlay";
  const calloutLayer = layer === "overlay" && (
    <div className={`compare-3d-callouts${column ? " compare-3d-callouts-column" : ""}`} data-ui-allow="overlap clip">
      {column && points && (
        <svg className="compare-3d-leaders" aria-hidden="true" width={size.width} height={size.height}>
          {callouts.map((callout, index) => {
            const target = targetOf(callout, points);
            if (!target) return null;
            const top = PLAQUE_TOP + index * PLAQUE_STEP;
            return (
              <line
                key={callout.id}
                x1={size.width - EDGE - PLAQUE_WIDTH}
                y1={top + 22}
                x2={target.x}
                y2={target.y}
                className={callout.primary ? "compare-3d-leader-primary" : "compare-3d-leader"}
              />
            );
          })}
        </svg>
      )}
      <ol className="compare-3d-plaques">
        {callouts.map((callout, index) => (
          <li
            key={callout.id}
            className={`compare-3d-plaque${callout.primary ? " compare-3d-plaque-primary" : ""}`}
            style={column ? { top: PLAQUE_TOP + index * PLAQUE_STEP } : undefined}
            data-testid={callout.primary ? "compare-3d-label" : "compare-3d-secondary"}
          >
            <span className="compare-3d-plaque-title">{callout.lines[0]}</span>
            <span className="compare-3d-plaque-fact">{callout.lines[1]}</span>
          </li>
        ))}
      </ol>
    </div>
  );
  return (
    <div className="compare-3d" data-testid="compare-3d" data-ui-allow="overlap clip">
      <div className="compare-3d-stack">
        <div className="compare-3d-stage">
          <div
            className="compare-3d-host"
            ref={host}
            role="img"
            aria-label={`${diff.sheet} ${diff.title} in 3D, Rev ${diff.from_rev} against Rev ${diff.to_rev}. Drag to rotate, scroll to zoom.`}
          />
          {column && calloutLayer}
          <p className="compare-3d-hint small">Drag to rotate, scroll to zoom</p>
        </div>
        {!column && calloutLayer}
      </div>
      <ViewerControls viewer={viewer} />
      {directory.length > 0 && (
        <section className="compare-3d-directory" data-testid="compare-3d-directory">
          <div>
            <h3>Affected units</h3>
            <ul>
              {directory.map((row) => (
                <li key={row.name}>
                  <strong>{row.name}</strong>
                  <span className="compare-3d-meta">{row.meta}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3>What the change touches</h3>
            <ul>
              {tasks.map((task) => (
                <li key={task.id}>
                  <strong>{task.name}</strong>
                  <span className="compare-3d-meta">{taskMeta(task)}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </div>
  );
}

/** Where a callout's leader line ends: the changed wall, the room of its unit, or the plate itself. */
function targetOf(callout: Callout, points: ScreenPoints): ScreenPoint | null {
  if (callout.target === "wall") return points.primary;
  const room = points.rooms[(callout.target.label ?? "").toUpperCase()];
  return room ?? points.plates[0] ?? null;
}
