import { Link } from "react-router-dom";
import { api, type Decision, type InboundEvent, type OutboundMessage, type RecordEntry, type StartCheck } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { autonomyCounts, autonomousActions, humanDecisions, type AutonomyEntry } from "../../api/counts";
import { formatTime } from "../../components/format";

const POLL_MS = 3000;

/** The one line the jury reads: how much Aurora did alone, how much a human decided. */
export function Autonomy() {
  const events = useQuery(api.events, [], { poll: POLL_MS, empty: [] as InboundEvent[] });
  const outbox = useQuery(api.outbox, [], { poll: POLL_MS, empty: [] as OutboundMessage[] });
  const decisions = useQuery(api.decisions, [], { poll: POLL_MS, empty: [] as Decision[] });
  const record = useQuery(api.record, [], { poll: POLL_MS, empty: [] as RecordEntry[] });
  const known = [events, outbox, decisions, record].every((query) => query.data !== undefined);

  const failed = [events, outbox, decisions, record].find((query) => query.error);
  if (failed) {
    return (
      <section className="autonomy" data-testid="overview-autonomy" aria-label="Autonomy">
        <p className="muted small">Actions on its own and decisions by a human: unavailable. {failed.error}</p>
      </section>
    );
  }
  if (!known) {
    return (
      <section className="autonomy" data-testid="overview-autonomy" aria-label="Autonomy">
        <p className="muted small">Actions on its own and decisions by a human: unavailable while the record loads.</p>
      </section>
    );
  }
  const counts = autonomyCounts(events.data ?? [], outbox.data ?? [], decisions.data ?? []);
  const actions = autonomousActions(outbox.data ?? [], record.data ?? []);
  const decided = humanDecisions(decisions.data ?? [], record.data ?? []);
  return (
    <section className="autonomy" data-testid="overview-autonomy" aria-label="Autonomy">
      <p className="autonomy-line">
        Aurora acted on its own{" "}
        <Count id="auto" value={counts.auto} one="time" many="times" entries={actions} />, a human decided{" "}
        <Count id="human" value={counts.human} one="time" many="times" entries={decided} />.
      </p>
    </section>
  );
}

function Count({
  id,
  value,
  one,
  many,
  entries,
}: {
  id: string;
  value: number;
  one: string;
  many: string;
  entries: AutonomyEntry[];
}) {
  return (
    <details className="autonomy-count" data-testid={`overview-autonomy-${id}`}>
      <summary>
        <span className="num autonomy-number">{value}</span> {value === 1 ? one : many}
      </summary>
      {entries.length === 0 ? (
        <p className="muted small">Nothing counted yet.</p>
      ) : (
        <ul className="autonomy-entries">
          {entries.slice(0, 6).map((entry) => (
            <li key={entry.key}>
              <a href={entry.href} target="_blank" rel="noreferrer">
                {entry.title}
              </a>
              <span className="muted small num"> {formatTime(entry.at)}</span>
            </li>
          ))}
        </ul>
      )}
      {entries.length > 6 && <p className="muted small">and {entries.length - 6} older not shown.</p>}
    </details>
  );
}

/** The newest start checks: a person, an agent or a robot asked, and Aurora answered. */
export function StartChecks() {
  const checks = useQuery(api.checks, [], { poll: POLL_MS, empty: [] as StartCheck[] });
  const rows = (checks.data ?? []).slice(0, 4);
  return (
    <section className="panel start-checks" data-testid="overview-start-checks" aria-label="Start checks">
      <div className="panel-head">
        <h2>Start checks</h2>
        <Link className="back-link" to="/robot">
          Ask the robot
        </Link>
      </div>
      {rows.length === 0 ? (
        <p className="muted small">No start check yet.</p>
      ) : (
        <ul className="autonomy-entries">
          {rows.map((check) => (
            <li key={check.id}>
              <Link to="/robot">
                <strong>{check.asked_by}</strong> asked to start {check.task_id ?? check.unit ?? "an unknown task"}:{" "}
                {check.allowed}
              </Link>
              {(check.reasons ?? [])[0] && <span className="muted small"> {(check.reasons ?? [])[0].text}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
