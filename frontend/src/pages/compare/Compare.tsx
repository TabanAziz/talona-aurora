import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type DiffRegion, type DrawingDiff, type WaitingItem } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { formatTime, humanize } from "../../components/format";
import { Async } from "../../components/States";
import { Compare3D } from "../compare3d/Compare3D";
import { webglAvailable } from "../../components/plan3d/scene";
import { Immersive } from "../../components/immersive/Immersive";
import "./compare.css";

type Mode = "before" | "after" | "overlay";
const MODES: Mode[] = ["before", "after", "overlay"];
const ZOOM_STEPS = [1, 1.5, 2, 3];

export function Compare() {
  const { id = "" } = useParams();
  const diff = useQuery(() => api.diff(id), [id]);

  return (
    <Async query={diff} rows={4}>
      {(data) => <CompareBody diff={data} />}
    </Async>
  );
}

function CompareBody({ diff }: { diff: DrawingDiff }) {
  const [params] = useSearchParams();
  const hasGeometry = Boolean(diff.before_geometry_url && diff.after_geometry_url);
  const [mode, setMode] = useState<Mode>("overlay");
  const [dimension, setDimension] = useState<"2d" | "3d">(params.get("view") === "3d" && hasGeometry && webglAvailable() ? "3d" : "2d");
  const [note, setNote] = useState<string | null>(null);
  const [zoomStep, setZoomStep] = useState(0);
  const zoom = ZOOM_STEPS[zoomStep];
  const regions = diff.regions ?? [];
  const src = mode === "before" ? diff.before_url : mode === "after" ? diff.after_url : diff.overlay_url;
  const shown = mode === "before" ? `Rev ${diff.from_rev}` : mode === "after" ? `Rev ${diff.to_rev}` : "overlay";

  return (
    <div className="compare" data-testid="compare-view">
      <div className="compare-work">
        <nav className="compare-crumbs small" aria-label="Breadcrumb">
          <Link to="/">Today</Link>
          <span className="faint" aria-hidden="true">
            /
          </span>
          <span>
            {diff.sheet}, {diff.title}
          </span>
        </nav>

        <Immersive title={`${diff.sheet}, Rev ${diff.from_rev} to Rev ${diff.to_rev}`} testId="compare">
        <div className="compare-bar">
          <div className="segmented" role="group" aria-label="Revision shown">
            {MODES.map((value) => (
              <button
                key={value}
                type="button"
                data-testid={`compare-${value}`}
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {value === "before" ? `Before, Rev ${diff.from_rev}` : value === "after" ? `After, Rev ${diff.to_rev}` : "Overlay"}
              </button>
            ))}
          </div>

          <div className="segmented compare-dim" role="group" aria-label="View">
            <button type="button" aria-pressed={dimension === "2d"} data-testid="compare-2d" onClick={() => setDimension("2d")}>
              2D
            </button>
            {hasGeometry && <button
              type="button"
              aria-pressed={dimension === "3d"}
              disabled={!hasGeometry}
              title={hasGeometry ? undefined : "This sheet has no geometry for a 3D view"}
              data-testid="compare-3d-switch"
              onClick={() => {
                if (webglAvailable()) {
                  setNote(null);
                  setDimension("3d");
                } else {
                  setNote("The 3D view needs WebGL, which this browser does not offer. The 2D drawing shows the same change.");
                }
              }}
            >
              3D
            </button>}
          </div>

          {mode === "overlay" && (
            <ul className="compare-legend small" aria-label="Legend">
              <li>
                <i className="compare-swatch compare-swatch-old" aria-hidden="true" />
                Rev {diff.from_rev} position
              </li>
              <li>
                <i className="compare-swatch compare-swatch-new" aria-hidden="true" />
                Rev {diff.to_rev} position
              </li>
            </ul>
          )}

          {dimension === "2d" && (
            <div className="compare-zoom" role="group" aria-label="Zoom">
              <button
                type="button"
                aria-label="Zoom out"
                data-testid="compare-zoom-out"
                disabled={zoomStep === 0}
                onClick={() => setZoomStep(zoomStep - 1)}
              >
                −
              </button>
              <span className="num" data-testid="compare-zoom-value">
                {Math.round(zoom * 100)}%
              </span>
              <button
                type="button"
                aria-label="Zoom in"
                data-testid="compare-zoom-in"
                disabled={zoomStep === ZOOM_STEPS.length - 1}
                onClick={() => setZoomStep(zoomStep + 1)}
              >
                +
              </button>
            </div>
          )}
        </div>

        {note && (
          <p className="muted small" role="status" data-testid="compare-3d-note">
            {note}
          </p>
        )}

        {dimension === "3d" ? (
          <Compare3D
            diff={diff}
            layer={mode}
            onUnavailable={() => {
              setDimension("2d");
              setNote("The 3D view could not start in this browser. The 2D drawing shows the same change.");
            }}
          />
        ) : (
          <div className="compare-stage" tabIndex={0} aria-label="Drawing, scroll to move when zoomed in">
            {/* Regions are fractions of the sheet, so they sit on top of the image by design. */}
            <figure className="compare-sheet" style={{ width: `${zoom * 100}%` }} data-ui-allow="overlap">
              <img data-testid="compare-image" src={src} alt={`${diff.sheet} ${diff.title}, ${shown}`} />
              {mode === "overlay" && regions.map((region, index) => <Region key={index} region={region} unmeasured={!hasGeometry} />)}
            </figure>
          </div>
        )}
        </Immersive>
      </div>

      <aside className="panel compare-side" data-testid="compare-panel">
        <div className="stack compare-head">
          <h1>
            {diff.sheet}, Rev {diff.from_rev} to Rev {diff.to_rev}
          </h1>
          <p className="muted small">{diff.title}</p>
        </div>

        <section className="stack">
          <h2>Change summary</h2>
          <p>{diff.summary ?? <span className="muted">unavailable</span>}</p>
          {regions.length === 0 ? (
            <p className="muted">No changed areas were found.</p>
          ) : (
            <ul className="compare-rows" data-testid="compare-changes">
              {regions.map((region, index) => (
                <li key={index}>
                  <span>{region.label ?? "Changed area"}</span>
                  <span className="muted small">{hasGeometry ? humanize(region.kind) : "From PDF"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <OutdatedSheets diff={diff} />
        <AffectedCrews diff={diff} />
        <Link className="button" to={`/notice/${diff.id}`} data-testid="compare-notice-link">
          Proof of notice
        </Link>
        <Link className="button" to="/robot" data-testid="compare-robot-link">
          See the layout robot
        </Link>
        <Revisions diff={diff} />
      </aside>
    </div>
  );
}

function Region({ region, unmeasured }: { region: DiffRegion; unmeasured: boolean }) {
  // the label grows toward the middle of the sheet and below a region near the top, so it stays on the sheet
  const below = region.y < 0.12;
  const start = region.x + region.w / 2 < 0.5;
  return (
    <span
      className={`compare-region compare-region-${region.kind}`}
      data-testid="compare-region"
      style={{
        left: `${region.x * 100}%`,
        top: `${region.y * 100}%`,
        width: `${region.w * 100}%`,
        height: `${region.h * 100}%`,
      }}
    >
      {!unmeasured && <span
        className={`compare-region-label${below ? " compare-region-label-below" : ""}${start ? " compare-region-label-start" : ""}`}
      >
        {region.label ?? humanize(region.kind)}
      </span>}
    </span>
  );
}

function mentionsRevision(item: WaitingItem, diff: DrawingDiff) {
  const text = item.what.toLowerCase();
  return text.includes(diff.sheet.toLowerCase()) && text.includes(`rev ${diff.to_rev}`.toLowerCase());
}

/** Other sheets that still show a wall this change moved, from the cross-sheet check's record entries. */
function OutdatedSheets({ diff }: { diff: DrawingDiff }) {
  const record = useQuery(api.record, []);
  return (
    <Async query={record} rows={2}>
      {(entries) => {
        const outdated = entries.filter(
          (entry) => entry.kind === "change" && entry.refs?.source_change === diff.id && entry.refs?.outdated_sheet,
        );
        if (outdated.length === 0) return null;
        return (
          <section className="stack">
            <h2>Sheets this change leaves out of date</h2>
            <ul className="compare-outdated" data-testid="compare-outdated">
              {outdated.map((entry) => (
                <li key={entry.id} data-testid="compare-outdated-sheet" data-sheet={entry.refs?.outdated_sheet}>
                  <Link
                    className="compare-outdated-link"
                    to={`/sheet/${encodeURIComponent(entry.refs?.outdated_sheet ?? "")}/${encodeURIComponent(entry.refs?.revision ?? "")}`}
                  >
                    {entry.refs?.outdated_sheet} Rev {entry.refs?.revision}
                  </Link>
                  <span className="muted small">{entry.detail}</span>
                </li>
              ))}
            </ul>
          </section>
        );
      }}
    </Async>
  );
}

function AffectedCrews({ diff }: { diff: DrawingDiff }) {
  const waiting = useQuery(api.waiting, []);
  return (
    <section className="stack">
      <h2>Affected crews</h2>
      <Async query={waiting} rows={2}>
        {(items) => {
          const crews = items.filter((item) => mentionsRevision(item, diff));
          if (crews.length === 0) return <p className="muted">No crew has been asked to confirm this revision.</p>;
          return (
            <ul className="compare-crews" data-testid="compare-crews">
              {crews.map((item) => {
                const confirmed = item.status === "done";
                return (
                  <li key={item.id} data-testid="compare-crew" data-status={item.status}>
                    <span className={confirmed ? "compare-ok" : "compare-bad"}>
                      {item.on}: {confirmed ? "confirmed" : "not confirmed"}
                    </span>
                    <span className="muted small">
                      Asked <span className="num">{formatTime(item.since)}</span>
                      {!confirmed && item.due && (
                        <>
                          , needed by <span className="num">{formatTime(item.due)}</span>
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          );
        }}
      </Async>
    </section>
  );
}

function Revisions({ diff }: { diff: DrawingDiff }) {
  const diffs = useQuery(api.diffs, []);
  return (
    <section className="stack">
      <h2>Revisions of this sheet</h2>
      <Async query={diffs} rows={2}>
        {(all) => {
          const revisions = new Set<string>([diff.from_rev, diff.to_rev]);
          for (const other of all) {
            if (other.sheet !== diff.sheet) continue;
            revisions.add(other.from_rev);
            revisions.add(other.to_rev);
          }
          const ordered = [...revisions].sort().reverse();
          return (
            <ol className="compare-revs" data-testid="compare-revisions">
              {ordered.map((rev, index) => {
                const introduced = all.find((other) => other.sheet === diff.sheet && other.to_rev === rev);
                return (
                  <li key={rev}>
                    <strong>Rev {rev}</strong>
                    <span className="muted small">
                      {introduced && introduced.id !== diff.id ? (
                        <Link to={`/compare/${introduced.id}`}>Compare with Rev {introduced.from_rev}</Link>
                      ) : rev === diff.from_rev ? (
                        "Replaced by this change"
                      ) : rev === diff.to_rev ? (
                        "Shown here"
                      ) : null}
                    </span>
                    <Link className="compare-label small" to={`/sheet/${diff.sheet}/${rev}/label`}>
                      Label
                    </Link>
                    <Link className="compare-label small" to={`/sheet/${diff.sheet}/${rev}`} data-testid="compare-status">
                      Status
                    </Link>
                    {index === 0 ? <span className="compare-tag compare-tag-current">Current</span> : <span />}
                  </li>
                );
              })}
            </ol>
          );
        }}
      </Async>
    </section>
  );
}
