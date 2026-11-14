import { Link, useParams } from "react-router-dom";
import { api, type DrawingDiff, type OutboundMessage, type Project, type WaitingItem } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { formatTime } from "../../components/format";
import { Async, Empty } from "../../components/States";
import { unconfirmed, verdict, type SheetStatusKind } from "./sheetState";
import "./sheet.css";

const POLL_MS = 3000;

interface SheetData {
  project: Project;
  diffs: DrawingDiff[];
  waiting: WaitingItem[];
  outbox: OutboundMessage[];
}

const TONE: Record<SheetStatusKind, "danger" | "success" | "neutral" | "warning"> = {
  superseded: "danger",
  current: "success",
  unreported: "neutral",
  unknown: "warning",
};

const LABEL: Record<SheetStatusKind, string> = {
  superseded: "Superseded",
  current: "Current",
  unreported: "No newer revision on record",
  unknown: "Unknown sheet",
};

export function labelPath(sheet: string, revision: string) {
  return `/sheet/${encodeURIComponent(sheet)}/${encodeURIComponent(revision)}/label`;
}

export function SheetStatus() {
  const { sheet = "", revision = "" } = useParams();
  const forced = useForcedState();
  const data = useQuery<SheetData>(
    async () => {
      const [project, diffs, waiting, outbox] = await Promise.all([api.project(), api.diffs(), api.waiting(), api.outbox()]);
      return { project, diffs, waiting, outbox };
    },
    [],
    { poll: POLL_MS },
  );

  if (!sheet.trim() || !revision.trim() || forced === "empty") {
    return <Empty>This link names no sheet revision.</Empty>;
  }
  return (
    <Async query={data} rows={4}>
      {(loaded) => <SheetBody data={loaded} sheet={sheet} revision={revision} />}
    </Async>
  );
}

function SheetBody({ data, sheet, revision }: { data: SheetData; sheet: string; revision: string }) {
  const state = verdict(data.project, data.diffs, sheet, revision);
  const asked = unconfirmed(data.waiting, state.sheet, state.currentRev);
  // A machine has no crew conversation; the notice it was sent on the machine channel is what makes it a machine here.
  const machineNames = new Set(data.outbox.filter((message) => message.channel === "machine").map((message) => message.to));
  const crewItems = asked.filter((item) => !machineNames.has(item.on));
  const machineItems = asked.filter((item) => machineNames.has(item.on));
  const superseded = state.kind === "superseded" && state.diff !== undefined;
  // A superseded label needs the change that replaced it, a current one the change that introduced it.
  const comparison = state.diff ?? state.introducedBy;

  return (
    <article className="sheet-view" data-testid="sheet-view">
      <section className={`sheet-band sheet-band-${state.kind}`} data-testid="sheet-status" data-status={state.kind}>
        <div className="sheet-band-head">
          <p className="sheet-band-kicker">
            {state.sheet}, revision {state.revision}
          </p>
          <Badge tone={TONE[state.kind]}>{LABEL[state.kind]}</Badge>
        </div>
        <h1>{headline(state.kind, state.currentRev)}</h1>
        <p className="sheet-band-detail">{detail(state.kind, state.sheet, state.revision, state.currentRev)}</p>
        <dl className="sheet-band-facts small">
          <div>
            <dt className="muted">This revision</dt>
            <dd className="num">Rev {state.revision}</dd>
          </div>
          <div>
            <dt className="muted">{state.kind === "superseded" ? "Current revision" : "Newest on record"}</dt>
            <dd className="num" data-testid="sheet-current-rev">
              Rev {state.currentRev}
            </dd>
          </div>
          <div>
            <dt className="muted">Reloads</dt>
            <dd className="num">every {POLL_MS / 1000} s</dd>
          </div>
        </dl>
      </section>

      <div className="sheet-actions">
        <Link className="button button-primary" to={labelPath(state.sheet, state.revision)} data-testid="sheet-label-link">
          Print the label for Rev {state.revision}
        </Link>
        {comparison && (
          <Link className="button" to={`/compare/${comparison.id}`} data-testid="sheet-actions-compare">
            Open the comparison
          </Link>
        )}
      </div>

      <div className="sheet-body">
        {superseded && state.diff ? (
          <Change diff={state.diff} />
        ) : (
          <section className="panel sheet-panel">
            <h2>What this page says</h2>
            <p>
              {state.kind === "current"
                ? `Rev ${state.currentRev} is the newest revision of ${state.sheet} on record. A later drawing change moves the band to red and names the revision to use instead.`
                : state.kind === "unknown"
                  ? `The project does not know ${state.sheet}. Check the sheet id on the label and scan it again.`
                  : `No drawing change names Rev ${state.revision} of ${state.sheet}, so nothing here says it was replaced. The site office keeps the revision register.`}
            </p>
          </section>
        )}

        <section className="panel sheet-panel" data-testid="sheet-crews">
          <div className="panel-head">
            <h2>Crews not confirmed</h2>
            <span className="panel-aside">{crewItems.length}</span>
          </div>
          {crewItems.length === 0 ? (
            <p className="muted">
              {superseded
                ? `Every crew has confirmed Rev ${state.currentRev}.`
                : `No crew is waiting to confirm Rev ${state.currentRev}.`}
            </p>
          ) : (
            <ul className="sheet-crew-list">
              {crewItems.map((item) => (
                <li key={item.id}>
                  <span>{item.on}</span>
                  <span className="muted small">
                    {item.what}, asked <span className="num">{formatTime(item.since)}</span>
                    {item.due ? `, needed by ${formatTime(item.due)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {machineItems.length > 0 && (
            <p className="muted small sheet-machines" data-testid="sheet-machines">
              Machines not confirmed: {machineItems.map((item) => item.on).join(", ")}. Aurora asked{" "}
              {machineItems.length === 1 ? "it" : "them"} to confirm Rev {state.currentRev} and{" "}
              {machineItems.length === 1 ? "it has" : "they have"} not loaded it.
            </p>
          )}
        </section>
      </div>
    </article>
  );
}

function Change({ diff }: { diff: DrawingDiff }) {
  return (
    <section className="panel sheet-panel">
      <div className="panel-head">
        <h2>What changed</h2>
        <span className="panel-aside num">
          Rev {diff.from_rev} to Rev {diff.to_rev}
        </span>
      </div>
      {diff.summary ? <p>{diff.summary}</p> : <p className="muted">The change summary is unavailable.</p>}
      <figure className="sheet-shot">
        <img
          data-testid="sheet-overlay"
          src={diff.overlay_url}
          alt={`The change from Rev ${diff.from_rev} to Rev ${diff.to_rev} on ${diff.sheet}, in the overlay`}
        />
      </figure>
      <Link className="button" to={`/compare/${diff.id}`} data-testid="sheet-compare-link">
        Open the comparison
      </Link>
    </section>
  );
}

function headline(kind: SheetStatusKind, currentRev: string) {
  if (kind === "superseded") return `Superseded by Rev ${currentRev}`;
  if (kind === "current") return "Current revision";
  if (kind === "unreported") return "No newer revision on record";
  return "Unknown sheet";
}

function detail(kind: SheetStatusKind, sheet: string, revision: string, currentRev: string) {
  if (kind === "superseded") return `Rev ${currentRev} is the newest revision of ${sheet}. Use Rev ${currentRev} or scan the current label on site.`;
  if (kind === "current") return `Aurora has no newer revision of ${sheet} than Rev ${revision}, so this label may be built from.`;
  if (kind === "unreported") return `The project has ${sheet}, but no drawing change names this revision. Ask the site office before you build from it.`;
  return `${sheet} is not one of this project's drawing sheets. Check the sheet id on the label and scan it again.`;
}
