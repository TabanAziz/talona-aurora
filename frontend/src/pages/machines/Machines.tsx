import { Link } from "react-router-dom";
import { api, type StartCheck } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { formatTime } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import { askerKind } from "../flag/stopped";
import "./machines.css";

const POLL_MS = 10000;

type MachineState = "working" | "waiting" | "stopped";
type Kind = "person" | "agent" | "robot";

interface Machine {
  name: string;
  kind: Kind;
  state: MachineState;
  latest: StartCheck;
  questions: number;
}

const STATE_LABEL: Record<MachineState, string> = {
  working: "Cleared to start",
  waiting: "Waiting",
  stopped: "Start blocked",
};

const STATE_TONE: Record<MachineState, "success" | "warning" | "danger"> = {
  working: "success",
  waiting: "warning",
  stopped: "danger",
};

const KIND_LABEL: Record<Kind, string> = {
  person: "Person",
  agent: "Agent",
  robot: "Robot",
};

/** The newest question decides what a machine is doing: cleared to start, held by a blocking reason, or waiting. */
function machineState(check: StartCheck): MachineState {
  if (check.allowed === "yes") return "working";
  if ((check.reasons ?? []).some((reason) => reason.blocking)) return "stopped";
  return "waiting";
}

/** One row per asker, newest question first. */
export function machinesFrom(checks: StartCheck[]): Machine[] {
  const newest = new Map<string, StartCheck>();
  const questions = new Map<string, number>();
  for (const check of checks) {
    questions.set(check.asked_by, (questions.get(check.asked_by) ?? 0) + 1);
    const seen = newest.get(check.asked_by);
    if (!seen || check.checked_at > seen.checked_at) newest.set(check.asked_by, check);
  }
  return [...newest.values()]
    .sort((left, right) => (left.checked_at < right.checked_at ? 1 : -1))
    .map((latest) => ({
      name: latest.asked_by,
      kind: askerKind(latest.asked_by),
      state: machineState(latest),
      latest,
      questions: questions.get(latest.asked_by) ?? 1,
    }));
}

export function Machines() {
  const forced = useForcedState();
  const checks = useQuery(api.checks, [], { poll: POLL_MS });
  const registry = useQuery(api.machines, [], { poll: POLL_MS });
  const machines = checks.data === undefined ? [] : machinesFrom(checks.data);
  const unasked = (registry.data ?? []).filter((item) => !machines.some((machine) => machine.name.trim().toLowerCase() === item.id.toLowerCase()));

  return (
    <article className="machines" data-testid="machines-view">
      <header className="machines-head">
        <h1>Equipment</h1>
        <p className="muted">
          Registered equipment and its latest permission to start. A clearance reflects the project record, not physical tracking.
        </p>
      </header>
      {checks.error || registry.error ? <ErrorState message={checks.error || registry.error || "Equipment is unavailable"} onRetry={() => { checks.reload(); registry.reload(); }} />
        : checks.loading || registry.loading || checks.data === undefined || registry.data === undefined ? <Loading rows={5} />
        : forced === "empty" || machines.length === 0 && unasked.length === 0 ? <Empty>No equipment has been registered for this project. <Link to="/drawings">Open the project plans</Link></Empty>
        : <ul className="machines-list">
        {unasked.map((machine) => <li key={machine.id} className="machines-row machines-registered" data-testid="machines-row" data-kind={machine.kind} data-state="registered">
          <div className="machines-row-head"><strong>{machine.name}</strong><Badge tone="neutral">Registered</Badge><span className="muted small">{machine.kind}</span></div>
          <p>No start request yet. Open a view to check what this equipment may do.</p>
          <dl className="machines-facts small"><div><dt>Work areas</dt><dd>{(machine.units ?? []).join(", ") || "Not assigned"}</dd></div><div><dt>Drawing sheets</dt><dd>{(machine.sheets ?? []).join(", ") || "Not assigned"}</dd></div></dl>
          <div className="machines-links">{machine.kind === "robot" && <Link className="button" to="/robot">Open layout robot</Link>}{machine.kind === "drone" && <Link className="button" to="/drone">Open survey drone</Link>}{machine.kind === "sensor" && <Link className="button" to="/site">Open site context</Link>}</div>
        </li>)}
        {machines.map((machine) => (
          <MachineRow key={machine.name} machine={machine} />
        ))}
      </ul>}
    </article>
  );
}

function MachineRow({ machine }: { machine: Machine }) {
  const reason = machine.latest.reasons?.[0];
  const flag = reason?.flag_id;
  return (
    <li
      className="machines-row"
      data-testid="machines-row"
      data-kind={machine.kind}
      data-state={machine.state}
    >
      <div className="machines-row-head">
        <strong>{machine.name}</strong>
        <span className="muted small">{KIND_LABEL[machine.kind]}</span>
        <Badge tone={STATE_TONE[machine.state]}>{STATE_LABEL[machine.state]}</Badge>
        <span className="muted small num">
          {machine.questions === 1 ? "1 question" : `${machine.questions} questions`}, last {formatTime(machine.latest.checked_at)}
        </span>
      </div>
      <p className="machines-question">{machine.latest.summary}</p>
      <p className="small">
        {reason ? reason.text : "Nothing stood in the way of starting."}
      </p>
      {machine.state === "stopped" && flag && (
        <p className="small muted">
          Held by flag <span className="num">{flag}</span>. The superintendent decides on that flag and can release the
          work.
        </p>
      )}
      <dl className="machines-facts small">
        <div>
          <dt className="muted">Task or unit</dt>
          <dd>{machine.latest.task_id || machine.latest.unit || "not named"}</dd>
        </div>
        <div>
          <dt className="muted">Confirmed revision and last report</dt>
          <dd className="muted">Not available yet</dd>
        </div>
      </dl>
      <div className="machines-links small">
        {flag && <Link to={`/flags/${encodeURIComponent(flag)}`}>Open the flag</Link>}
        {machine.kind === "robot" && <Link to="/robot">Robot view</Link>}
      </div>
    </li>
  );
}
