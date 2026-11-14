import { projectApiUrl } from "../../api/workspace";
import { Link, useParams } from "react-router-dom";
import { api, type DrawingDiff } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge, type Tone } from "../../components/Badge";
import { formatTime, humanize } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import { buildProof, type CrewProof, type MachineMoments, type Proof, type Step } from "./proof";
import "./notice.css";

const POLL_MS = 3000;

const DELIVERY_LABEL: Record<string, string> = {
  sent: "Sent",
  simulated: "Simulated",
  queued: "Queued",
  failed: "Not delivered",
};

const DELIVERY_TONE: Record<string, Tone> = {
  sent: "success",
  simulated: "neutral",
  queued: "neutral",
  failed: "danger",
};

export function Notice() {
  const { id = "" } = useParams();
  const forced = useForcedState();
  const diff = useQuery(() => api.diff(id), [id]);
  const outbox = useQuery(api.outbox, [], { poll: POLL_MS });
  const waiting = useQuery(api.waiting, [], { poll: POLL_MS });
  const record = useQuery(api.record, [], { poll: POLL_MS });
  const events = useQuery(api.events, [], { poll: POLL_MS });
  const queries = [diff, outbox, waiting, record, events];

  if (forced === "empty") return <Empty>No crew is affected by this change, so there is nothing to prove.</Empty>;
  const failed = queries.find((query) => query.error);
  if (failed) {
    return (
      <ErrorState
        message={failed.error ?? "Something went wrong."}
        onRetry={() => queries.forEach((query) => query.reload())}
      />
    );
  }
  if (queries.some((query) => query.data === undefined)) return <Loading rows={5} />;

  const change = diff.data as DrawingDiff;
  const proof = buildProof(change, outbox.data ?? [], waiting.data ?? [], record.data ?? [], events.data ?? []);
  // A unit whose work was built before this revision has its own evidence page, the attachment of the change order.
  const reworkUnits = [
    ...new Set(
      (record.data ?? [])
        .filter((entry) => entry.refs?.diff === change.id && entry.refs?.rework && entry.refs?.unit)
        .map((entry) => entry.refs?.unit as string),
    ),
  ];
  return <NoticeBody diff={change} proof={proof} reworkUnits={reworkUnits} />;
}

function NoticeBody({ diff, proof, reworkUnits }: { diff: DrawingDiff; proof: Proof; reworkUnits: string[] }) {
  // The consequence of the crews that have not confirmed, taken from the last step of their own trail.
  const open = proof.crews
    .filter((crew) => !crew.confirmed)
    .map((crew) => {
      const lastWarning = [...crew.steps].reverse().find((step) => step.warning);
      return {
        crew: crew.crew,
        machine: crew.machine !== null,
        warning: lastWarning ? lastWarning.detail ?? lastWarning.title : null,
      };
    });
  const machines = proof.crews.filter((crew) => crew.machine !== null).length;
  return (
    <article className="notice" data-testid="notice-view">
      <div className="notice-actions">
        <Link className="back-link" to={`/compare/${diff.id}`}>
          Back to the comparison
        </Link>
        <button type="button" className="button" data-testid="notice-print" onClick={() => window.print()}>
          Print this page
        </button>
      </div>

      <header className="panel notice-head">
        <p className="muted small">Proof of notice</p>
        <h1>
          {diff.sheet}, {diff.title}: Rev {diff.from_rev} to Rev {diff.to_rev}
        </h1>
        {diff.summary && <p>{diff.summary}</p>}
        <dl className="notice-facts small">
          <div>
            <dt className="muted">Revision arrived</dt>
            <dd className="row" data-testid="notice-arrival">
              <span>
                <span className="num">{proof.arrival ? formatTime(proof.arrival.at) : "unavailable"}</span>
                {proof.arrival?.actor && `, from ${proof.arrival.actor}`}
              </span>
              {proof.arrival?.eventId && <SourceLink eventId={proof.arrival.eventId} />}
            </dd>
          </div>
          <div>
            <dt className="muted">Crews affected</dt>
            <dd>{proof.crews.length - machines}</dd>
          </div>
          {machines > 0 && (
            <div>
              <dt className="muted">Machines affected</dt>
              <dd>{machines}</dd>
            </div>
          )}
        </dl>
        {open.length > 0 && (
          // The outcome of the crews that have not answered belongs in the first screen, not under the fold.
          <p className="notice-outcome" data-testid="notice-outcome">
            <strong>{outcomeText(open)}</strong>
            {open[0].warning ? `: ${open[0].warning}` : "."}
          </p>
        )}
      </header>

      {reworkUnits.length > 0 && (
        <div className="row small">
          <span className="muted">Work was reported before this change in:</span>
          {reworkUnits.map((unit) => (
            <Link
              key={unit}
              className="notice-rework-link"
              to={`/rework/${diff.id}/${encodeURIComponent(unit)}`}
              data-testid="notice-rework-link"
            >
              unit {unit}, rework evidence
            </Link>
          ))}
        </div>
      )}

      {proof.crews.length === 0 ? (
        <Empty>No crew is affected by this change, so there is nothing to prove.</Empty>
      ) : (
        proof.crews.map((crew) => <CrewBlock key={crew.crew} crew={crew} />)
      )}

      <footer className="notice-foot muted small">
        Generated from the Aurora record{proof.asOf ? `, as of ${formatTime(proof.asOf)} UTC` : ""}.
      </footer>
    </article>
  );
}

function outcomeText(open: { machine: boolean }[]): string {
  const count = (n: number, one: string, many: string) => (n === 1 ? `1 ${one}` : `${n} ${many}`);
  const machines = open.filter((item) => item.machine).length;
  const crews = open.length - machines;
  const verb = open.length === 1 ? "has" : "have";
  if (machines === 0) return `${count(crews, "crew", "crews")} ${verb} not confirmed`;
  if (crews === 0) return `${count(machines, "machine", "machines")} ${verb} not confirmed`;
  return `${count(crews, "crew", "crews")} and ${count(machines, "machine", "machines")} have not confirmed`;
}

function MachineBlock({ crew, machine }: { crew: CrewProof; machine: MachineMoments }) {
  // The proof of a machine is its three moments on one line; only an escalation adds rows, so the print keeps to A4.
  const extra = crew.steps.filter((step) => step.kind === "superintendent");
  const waiting = crew.steps.find((step) => step.kind === "not_confirmed");
  const moment = (at: string | null, missing: string) => (at ? `${formatTime(at)} UTC` : missing);
  return (
    <section
      className="panel notice-crew notice-machine"
      data-testid="notice-crew"
      data-crew={crew.crew}
      data-confirmed={crew.confirmed}
      data-machine="true"
    >
      <div className="panel-head">
        <h2>{crew.crew}</h2>
        <div className="row">
          <Badge>Simulated machine</Badge>
          <Badge tone={crew.confirmed ? "success" : "warning"}>{crew.confirmed ? "Confirmed" : "Not confirmed"}</Badge>
        </div>
      </div>
      <dl className="notice-moments small" data-testid="notice-machine">
        <div>
          <dt className="muted">Sent</dt>
          <dd className="num" data-testid="notice-sent">
            {moment(machine.sent, "time unavailable")}
            {machine.delivery && machine.delivery !== "sent" ? ` (${DELIVERY_LABEL[machine.delivery] ?? machine.delivery})` : ""}
          </dd>
        </div>
        <div>
          <dt className="muted">Received</dt>
          <dd className="num" data-testid="notice-received">{moment(machine.received, "not fetched yet")}</dd>
        </div>
        <div>
          <dt className="muted">Loaded</dt>
          <dd className="num" data-testid="notice-loaded">{moment(machine.loaded, "not loaded yet")}</dd>
        </div>
        {waiting?.detail && (
          <div>
            <dt className="muted">Work</dt>
            <dd className={waiting.warning ? "notice-warning" : undefined}>{waiting.detail}</dd>
          </div>
        )}
      </dl>
      {extra.length > 0 && (
        <ol className="notice-steps">
          {extra.map((step) => (
            <StepRow key={step.key} step={step} />
          ))}
        </ol>
      )}
    </section>
  );
}

function CrewBlock({ crew }: { crew: CrewProof }) {
  if (crew.machine) return <MachineBlock crew={crew} machine={crew.machine} />;
  return (
    <section className="panel notice-crew" data-testid="notice-crew" data-crew={crew.crew} data-confirmed={crew.confirmed}>
      <div className="panel-head">
        <h2>{crew.crew}</h2>
        <Badge tone={crew.confirmed ? "success" : "warning"}>{crew.confirmed ? "Confirmed" : "Not confirmed"}</Badge>
      </div>
      <ol className="notice-steps">
        {crew.steps.map((step) => (
          <StepRow key={step.key} step={step} />
        ))}
      </ol>
    </section>
  );
}

function StepRow({ step }: { step: Step }) {
  return (
    <li className={`notice-step notice-step-${step.kind}`} data-testid="notice-step" data-kind={step.kind} data-warning={step.warning}>
      <span className="notice-dot" aria-hidden="true" />
      <div className="notice-step-body">
        <div className="row">
          <strong>{step.title}</strong>
          {step.channel && <Badge>{humanize(step.channel)}</Badge>}
          {step.delivery && (
            <Badge tone={DELIVERY_TONE[step.delivery] ?? "neutral"}>
              {DELIVERY_LABEL[step.delivery] ?? step.delivery}
            </Badge>
          )}
        </div>
        {(step.at || step.kind !== "not_confirmed") && (
          <span className="notice-time num small muted">{step.at ? `${formatTime(step.at)} UTC` : "time unavailable"}</span>
        )}
        {step.detail && (
          <p className={step.kind === "confirmed" ? "notice-quote" : step.warning ? "notice-warning" : "muted"}>
            {step.kind === "confirmed" ? `"${step.detail}"` : step.detail}
          </p>
        )}
        {step.sourceEventId && <SourceLink eventId={step.sourceEventId} />}
      </div>
    </li>
  );
}

function SourceLink({ eventId }: { eventId: string }) {
  return (
    <a className="notice-source small" href={projectApiUrl(`/api/events/${encodeURIComponent(eventId)}`)} target="_blank" rel="noreferrer">
      Source {eventId}
    </a>
  );
}
