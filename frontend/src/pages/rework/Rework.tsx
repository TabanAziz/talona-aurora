import { projectApiUrl } from "../../api/workspace";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge, type Tone } from "../../components/Badge";
import { formatNumber, formatTime } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import { buildCase, gapText, hoursText, type CostLine, type ReworkCase, type ReworkStep } from "./case";
import "./rework.css";

const DELIVERY_TONE: Record<string, Tone> = {
  sent: "success",
  simulated: "neutral",
  queued: "neutral",
  failed: "danger",
};

const DELIVERY_LABEL: Record<string, string> = {
  sent: "Sent",
  simulated: "Simulated",
  queued: "Queued",
  failed: "Not delivered",
};

async function loadCase(diffId: string, unit: string): Promise<ReworkCase | null> {
  let diff;
  try {
    diff = await api.diff(diffId);
  } catch (error) {
    // A change nobody knows is not a broken page: it is a case that does not exist.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  const [record, outbox, waiting, plan, events] = await Promise.all([
    api.record(),
    api.outbox(),
    api.waiting(),
    api.plan(),
    api.events(),
  ]);
  return buildCase({ diff, unit, record, outbox, waiting, plan, events });
}

export function Rework() {
  const { diffId = "", unit = "" } = useParams();
  const forced = useForcedState();
  const query = useQuery(() => loadCase(diffId, unit), [diffId, unit]);

  if (forced === "empty") return <Empty>No rework case for this change and unit.</Empty>;
  if (query.error) return <ErrorState message={query.error} onRetry={query.reload} />;
  if (query.loading || query.data === undefined) return <Loading rows={6} />;
  if (query.data === null)
    return (
      <div className="rework-not-found" data-testid="rework-not-found">
        <Empty>
          Aurora has no rework case for this change and unit. A case exists only when the record shows work
          reported before the revision arrived. <Link to="/">Back to Today</Link>.
        </Empty>
      </div>
    );
  return <ReworkBody rework={query.data} />;
}

function ReworkBody({ rework }: { rework: ReworkCase }) {
  return (
    <article className="rework" data-testid="rework-view">
      <div className="rework-actions">
        <Link className="back-link" to="/">
          Back to Today
        </Link>
        <button type="button" className="button" data-testid="rework-print" onClick={() => window.print()}>
          Print this page
        </button>
      </div>

      <header className="panel rework-head">
        <p className="muted small">Rework evidence for a change order</p>
        <h1>Unit {rework.unit}: work reported before the drawing changed</h1>
        <p className="rework-summary" data-testid="rework-summary">
          {rework.summary}
        </p>
        <dl className="rework-facts small">
          <div>
            <dt className="muted">Between report and revision</dt>
            <dd className="num">{gapText(rework.hours)}</dd>
          </div>
          <div>
            <dt className="muted">Crew</dt>
            <dd>{rework.crew ?? "unavailable"}</dd>
          </div>
          <div>
            <dt className="muted">Task</dt>
            <dd>{rework.task ? `${rework.task.name} (${rework.task.id})` : "unavailable"}</dd>
          </div>
        </dl>
      </header>

      <section className="panel rework-timeline" aria-labelledby="rework-timeline-heading">
        <h2 id="rework-timeline-heading">What the record shows, in time order</h2>
        <ol className="rework-steps">
          {rework.steps.map((step) => (
            <StepRow
              key={step.key}
              step={step}
              change={rework.change}
              overlayUrl={rework.overlayUrl}
              unit={rework.unit}
            />
          ))}
        </ol>
      </section>

      <CostBox costs={rework.costs} totalHours={rework.totalHours} taskKnown={rework.task !== null} />

      <footer className="rework-foot muted small">Generated from the Aurora record.</footer>
    </article>
  );
}

function StepRow({
  step,
  change,
  overlayUrl,
  unit,
}: {
  step: ReworkStep;
  change: string | null;
  overlayUrl: string | null;
  unit: string;
}) {
  if (step.kind === "gap") {
    return (
      <li className="rework-step rework-step-gap" data-testid="rework-step" data-kind="gap">
        <span className="rework-dot" aria-hidden="true" />
        <div className="rework-step-body">
          <strong data-testid="rework-gap">{step.title}</strong>
          <span className="muted small">{step.detail}</span>
        </div>
      </li>
    );
  }
  return (
    <li
      className={`rework-step rework-step-${step.kind}`}
      data-testid="rework-step"
      data-kind={step.kind}
      data-warning={step.warning}
    >
      <span className="rework-dot" aria-hidden="true" />
      <div className="rework-step-body">
        <div className="row">
          <strong>{step.title}</strong>
          {step.channel && <Badge>{step.channel}</Badge>}
          {step.delivery && (
            <Badge tone={DELIVERY_TONE[step.delivery] ?? "neutral"}>
              {DELIVERY_LABEL[step.delivery] ?? step.delivery}
            </Badge>
          )}
        </div>
        <span className="rework-time num small muted">
          {step.at ? `${formatTime(step.at)} UTC` : "time unavailable"}
        </span>
        {step.detail && <p className="rework-detail muted small">{step.detail}</p>}
        {step.quote && <blockquote className="rework-quote">{step.quote}</blockquote>}
        {step.sourceEventId && <SourceLink eventId={step.sourceEventId} />}
        {step.kind === "revision" && overlayUrl && (
          <figure className="rework-overlay" data-testid="rework-overlay">
            <img src={overlayUrl} alt={`What changed on the drawing: ${change ?? "the marked area"}`} />
            <figcaption className="muted small">
              What changed in Unit {unit}: {change ? change.replace(/\.$/, "") : "unavailable"}. The marked area
              shows the old and the new position.
            </figcaption>
          </figure>
        )}
      </div>
    </li>
  );
}

function SourceLink({ eventId }: { eventId: string }) {
  return (
    <a
      className="rework-source small"
      data-testid="rework-source"
      href={projectApiUrl(`/api/events/${encodeURIComponent(eventId)}`)}
      target="_blank"
      rel="noreferrer"
    >
      Source {eventId}
    </a>
  );
}

/** A typed rate only. Nothing is stored and no amount appears until a rate is entered. */
function parseRate(value: string): number | null {
  const cleaned = value.trim().replace(",", ".");
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function CostBox({ costs, totalHours, taskKnown }: { costs: CostLine[]; totalHours: number | null; taskKnown: boolean }) {
  const [rate, setRate] = useState("");
  const parsed = parseRate(rate);
  const amount = parsed !== null && totalHours !== null ? parsed * totalHours : null;
  return (
    <section className="panel rework-cost" data-testid="rework-cost" aria-labelledby="rework-cost-heading">
      <div className="panel-head">
        <h2 id="rework-cost-heading">Cost of redoing the work once</h2>
        <span className="panel-aside">Assumption, not a measurement</span>
      </div>
      {taskKnown && costs.length > 0 ? (
        <ul className="rework-cost-list">
          {costs.map((line) => (
            <li key={line.id}>
              <span>
                {line.name}{" "}
                <span className="muted small">({line.dependent ? "depends on it" : "the work itself"})</span>
              </span>
              <span className="num">{line.hours === null ? "unavailable" : hoursText(line.hours)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">The plan holds no task for this work, so it gives no working hours for a redo.</p>
      )}
      <p className="rework-total">
        <strong>
          {totalHours === null ? "Rework hours unavailable" : `Rework hours: ${hoursText(totalHours)}`}
        </strong>
        {totalHours !== null && (
          <span className="muted small">, including the tasks that depend on it</span>
        )}
      </p>
      <div className="rework-rate">
        <label htmlFor="rework-hourly-rate">Hourly rate</label>
        <input
          id="rework-hourly-rate"
          className="rework-rate-input"
          data-testid="rework-rate"
          inputMode="decimal"
          placeholder="Type a rate"
          value={rate}
          onChange={(event) => setRate(event.target.value)}
        />
        <span className="rework-rate-print num">{parsed === null ? "not entered" : formatNumber(parsed)}</span>
      </div>
      <p className="rework-amount" data-testid="rework-amount">
        {amount !== null ? (
          <strong>Amount at that rate: {formatNumber(amount)}</strong>
        ) : parsed === null ? (
          <span className="muted">Type an hourly rate to see the amount. Nothing is stored.</span>
        ) : (
          <span className="muted">The hours are unavailable, so no amount can be shown.</span>
        )}
      </p>
    </section>
  );
}
