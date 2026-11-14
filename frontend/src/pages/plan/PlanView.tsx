import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, type Flag, type Plan, type Proposal, type ResourceLine, type Task, type TaskShift } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { proposalSummary } from "../../components/proposalSummary";
import { actionLabel, formatDay, formatNumber, formatRange, formatSigned, formatTime } from "../../components/format";
import { Async, Empty, ErrorState, Loading } from "../../components/States";
import { actualFor } from "./actual";
import { dayKey, locationLabel, TASK_STATUS, workName } from "./presentation";
import {
  barStyle,
  moveLabel,
  openRescheduleProposals,
  overlapsWeek,
  shiftLabel,
  weekDays,
  weekStartFor,
} from "./week";
import "./plan.css";

const POLL_MS = 3000;
const EMPTY_PLAN: Plan = { handover: "", tasks: [], resources: [] };
// Above this many tasks the chart keeps the changed and flagged ones and offers the rest on request.
const CHART_ROWS = 10;
const NOT_AFFECTED_ROWS = 4;
const WORK_PAGE_SIZE = 16;

export function PlanView() {
  const plan = useQuery(api.plan, [], { poll: POLL_MS, empty: EMPTY_PLAN });
  const flags = useQuery(api.flags, [], { poll: POLL_MS, empty: [] as Flag[] });
  const proposals = useQuery(api.proposals, [], { poll: POLL_MS, empty: [] as Proposal[] });

  function reloadAll() {
    plan.reload();
    flags.reload();
    proposals.reload();
  }

  return (
    <div className="plan" data-testid="plan-view">
      {flags.error && <ErrorState message={`Schedule warnings could not be loaded. ${flags.error}`} onRetry={flags.reload} />}
      <Async query={plan} rows={6}>
        {(data) => (
          <PlanBody
            plan={data}
            flags={flags.data ?? []}
            proposals={openRescheduleProposals(proposals.data ?? [])}
            proposalsState={{ loading: proposals.loading, error: proposals.error, reload: proposals.reload }}
            onDecided={reloadAll}
          />
        )}
      </Async>
    </div>
  );
}

interface BodyProps {
  plan: Plan;
  flags: Flag[];
  proposals: Proposal[];
  proposalsState: { loading: boolean; error: string | null; reload: () => void };
  onDecided: () => void;
}

function PlanBody({ plan, flags, proposals, proposalsState, onDecided }: BodyProps) {
  const tasks = plan.tasks ?? [];
  const resources = plan.resources ?? [];
  const weekStart = weekStartFor(tasks);
  const shifts = new Map(proposals.flatMap((p) => (p.shifts ?? []).map((s) => [s.task_id, s] as const)));
  const flaggedTasks = new Set(flags.map((f) => f.affected?.task).filter((t): t is string => Boolean(t)));
  const deviations = flags.filter((f) => f.type === "plan_deviation" && ["open", "held"].includes(f.status ?? "open"));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Schedule</h1>
          <p className="muted">Work, deliveries and the impact of reported delays. All times UTC.</p>
        </div>
        <div className="plan-kpi">
          <span className="muted small">Handover</span>
          <span className="plan-kpi-value" data-testid="plan-handover" title={plan.handover || undefined}>
            {formatDay(plan.handover)}
          </span>
        </div>
      </div>

      <div className="plan-grid">
        <div className="plan-main">
          <section className="panel plan-card" aria-labelledby="resources-heading">
            <div className="stack">
              <h2 id="resources-heading">Deliveries, equipment and crews</h2>
              <p className="muted small">Compare the scheduled arrival with the latest report. A reported date is not confirmation that an item has arrived.</p>
            </div>
            {resources.length === 0 ? (
              <Empty>No planned deliveries, equipment or crews yet.</Empty>
            ) : (
              <ul className="plan-resource-list" data-testid="plan-resources">
                    {[...resources].sort((a, b) => a.date.localeCompare(b.date) || a.item.localeCompare(b.item)).map((line) => (
                      <ResourceRow key={line.id} line={line} flags={flags} />
                    ))}
              </ul>
            )}
          </section>

          <WorkSchedule tasks={tasks} flags={flags} shifts={shifts} />

          <section className="panel plan-card" aria-labelledby="gantt-heading">
            <details className="plan-timeline-details">
              <summary id="gantt-heading">Weekly timeline</summary>
            <div className="plan-card-head">
              <p className="muted small">From {formatDay(new Date(weekStart).toISOString())}. Exact work dates are listed above.</p>
              <div className="plan-legend muted small" aria-hidden="true">
                <span className="plan-legend-item">
                  <span className="plan-swatch plan-swatch-original" />
                  Accepted schedule
                </span>
                {shifts.size > 0 && (
                  <span className="plan-legend-item">
                    <span className="plan-swatch plan-swatch-proposed" />
                    Proposed
                  </span>
                )}
              </div>
            </div>
            <WeekChart tasks={tasks} weekStart={weekStart} shifts={shifts} flaggedTasks={flaggedTasks} />
            </details>
          </section>
        </div>

        <aside className="plan-side" aria-label="Proposed plan change">
          {proposalsState.error ? (
            <ErrorState message={proposalsState.error} onRetry={proposalsState.reload} />
          ) : proposalsState.loading ? (
            <Loading rows={3} />
          ) : proposals.length === 0 ? (
            <section className="panel" data-testid="plan-proposal-empty">
              <h2>Changes awaiting approval</h2>
              <p className="muted">No plan change is waiting for a decision.</p>
            </section>
          ) : (
            proposals.map((proposal) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                flag={flags.find((f) => f.id === proposal.flag_id)}
                tasks={tasks}
                weekStart={weekStart}
                shiftedIds={new Set(shifts.keys())}
                onDecided={onDecided}
              />
            ))
          )}

          <section className="section" aria-labelledby="deviations-heading">
            <h2 id="deviations-heading">Reported schedule warnings</h2>
            {deviations.length === 0 ? (
              <Empty>No unresolved schedule warnings are recorded.</Empty>
            ) : (
              <ul className="list" data-testid="plan-deviations">
                {deviations.map((flag) => (
                  <li key={flag.id} className="plan-deviation" data-testid="plan-deviation">
                    <Link to={`/flags/${flag.id}`}>{flag.title}</Link>
                    <Badge tone={flag.status === "held" ? "warning" : "danger"}>{flag.status === "held" ? "On hold" : "Open warning"}</Badge>
                    <p className="small">{flag.summary}</p>
                    {flag.evidence?.[0] && <p className="muted small">{flag.evidence[0].sender}: “{flag.evidence[0].quote}”</p>}
                    <Link className="small" to={`/flags/${flag.id}`}>Read report and sources</Link>
                    <span className="muted small" title={flag.work_starts_at ?? undefined}>
                      Work starts {formatTime(flag.work_starts_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

function WorkSchedule({ tasks, flags, shifts }: { tasks: Task[]; flags: Flag[]; shifts: Map<string, TaskShift> }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [requestedDay, setRequestedDay] = useState("");
  const [limit, setLimit] = useState(WORK_PAGE_SIZE);
  const matchingFlags = (task: Task) => flags.filter((flag) => flag.affected?.task === task.id && ["open", "held"].includes(flag.status ?? "open"));
  const matching = [...tasks].filter((task) => {
    if (filter === "remaining" && task.status === "done") return false;
    if (filter === "attention" && !shifts.has(task.id) && task.status !== "on_hold" && matchingFlags(task).length === 0) return false;
    return `${workName(task.name, task)} ${task.name} ${task.crew} ${task.unit ?? ""}`.toLowerCase().includes(query.toLowerCase());
  }).sort((a, b) => a.start.localeCompare(b.start) || a.name.localeCompare(b.name));
  const dayCounts = new Map<string, number>();
  for (const task of matching) {
    const day = dayKey(task.start);
    dayCounts.set(day, (dayCounts.get(day) ?? 0) + 1);
  }
  const nextWork = matching.find((task) => task.status !== "done" && new Date(task.end).getTime() >= Date.now())
    ?? matching.find((task) => task.status !== "done") ?? matching[0];
  const defaultDay = nextWork ? dayKey(nextWork.start) : "all";
  const selectedDay = requestedDay === "all" || dayCounts.has(requestedDay) ? requestedDay : defaultDay;
  const onDay = selectedDay === "all" ? matching : matching.filter((task) => dayKey(task.start) === selectedDay);
  const visible = onDay.slice(0, limit);
  useEffect(() => { setLimit(WORK_PAGE_SIZE); }, [selectedDay, filter, query]);
  const groups = new Map<string, Task[]>();
  for (const task of visible) {
    const key = dayKey(task.start);
    groups.set(key, [...(groups.get(key) ?? []), task]);
  }

  return <section className="panel plan-card" aria-labelledby="work-heading">
    <div className="stack">
      <h2 id="work-heading">Work schedule</h2>
      <p className="muted small">Grouped by planned start day, in UTC. Proposed dates stay separate until a person accepts the change.</p>
    </div>
    <div className="plan-filters">
      <label>Planned start day (UTC)<select className="input" value={selectedDay} onChange={(event) => setRequestedDay(event.target.value)} data-testid="plan-day-filter">
        <option value="all">All days ({matching.length} tasks)</option>
        {[...dayCounts].map(([day, count]) => <option value={day} key={day}>{day === "Date unavailable" ? day : formatDay(`${day}T00:00:00Z`)} ({count} tasks)</option>)}
      </select></label>
      <label>Show<select className="input" value={filter} onChange={(event) => setFilter(event.target.value)}>
        <option value="all">All work</option><option value="remaining">Remaining work</option><option value="attention">Needs attention</option>
      </select></label>
      <label>Find work, crew or room<input className="input" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search the schedule" /></label>
    </div>
    <p className="muted small" aria-live="polite" data-testid="plan-work-count">Showing {visible.length} of {onDay.length} tasks {selectedDay === "all" ? "across all days" : "on this day"}. {matching.length} matching tasks across {dayCounts.size} days, {tasks.length} tasks in the full schedule. {selectedDay !== "all" && "Choose another day or All days to see later work."}</p>
    {visible.length === 0 ? <Empty>{tasks.length ? "No work matches these filters. Choose All work or clear the search." : "No work has been scheduled yet."}</Empty> :
      <div className="plan-agenda" data-testid="plan-work-schedule">{[...groups].map(([day, dayTasks]) => <section className="plan-day" key={day}>
        <h3>{day === "Date unavailable" ? day : formatDay(`${day}T00:00:00Z`)}</h3>
        <ul className="plan-work-list">{dayTasks.map((task) => {
          const shift = shifts.get(task.id);
          const warnings = matchingFlags(task);
          return <li className="plan-work" key={task.id} data-task-id={task.id}>
            <div className="plan-work-head"><strong title={task.name}>{workName(task.name, task)}</strong><Badge tone={task.status === "on_hold" ? "warning" : task.status === "done" ? "success" : "neutral"}>{TASK_STATUS[task.status ?? "planned"]}</Badge></div>
            <p className="muted small">{locationLabel(task.unit)} · Crew: {task.crew || "Not recorded"}</p>
            {(/^layout-/i.test(task.id) || /\brobot\b/i.test(task.crew)) && <p className="muted small">Robot layout work marks the wall positions on the floor.</p>}
            <dl className="plan-work-dates"><div><dt>Planned</dt><dd title={`${task.start} to ${task.end}`}>{formatRange(task.start, task.end)}</dd></div>
              {shift && <div className="plan-work-proposed"><dt>Proposed, awaiting approval</dt><dd>{formatRange(shift.new_start, shift.new_end)} <span className="small">({shiftLabel(shift)})</span></dd></div>}
            </dl>
            {(task.depends_on ?? []).length > 0 && <p className="muted small">After: {(task.depends_on ?? []).map((id) => { const dependency = tasks.find((item) => item.id === id); return dependency ? workName(dependency.name, dependency) : id; }).join(", ")}</p>}
            {warnings.map((flag) => <Link className="plan-work-warning small" key={flag.id} to={`/flags/${flag.id}`}>Warning: {flag.title}. View sources</Link>)}
          </li>;
        })}</ul>
      </section>)}</div>}
    {visible.length < onDay.length && <button type="button" className="button plan-more" data-testid="plan-work-more" onClick={() => setLimit((current) => current + WORK_PAGE_SIZE)}>Show {Math.min(WORK_PAGE_SIZE, onDay.length - visible.length)} more tasks ({onDay.length - visible.length} remaining)</button>}
    {limit > WORK_PAGE_SIZE && <button type="button" className="button plan-more" onClick={() => setLimit(WORK_PAGE_SIZE)}>Show first {WORK_PAGE_SIZE} tasks</button>}
  </section>;
}

interface ChartProps {
  tasks: Task[];
  weekStart: number;
  shifts: Map<string, TaskShift>;
  flaggedTasks: Set<string>;
}

function WeekChart({ tasks, weekStart, shifts, flaggedTasks }: ChartProps) {
  const [showAll, setShowAll] = useState(false);
  const days = weekDays(weekStart);
  const inWeek = tasks.filter((task) => overlapsWeek(task, weekStart) || shifts.has(task.id));
  if (inWeek.length === 0) return <Empty>No tasks are scheduled for this week.</Empty>;

  const rank = (task: Task) => (shifts.has(task.id) ? 0 : flaggedTasks.has(task.id) ? 1 : 2);
  const kept = showAll
    ? inWeek
    : [...inWeek].sort((a, b) => rank(a) - rank(b) || a.start.localeCompare(b.start) || a.id.localeCompare(b.id)).slice(0, CHART_ROWS);
  const rows = [...kept].sort((a, b) => a.start.localeCompare(b.start) || a.id.localeCompare(b.id));

  return (
    <>
      <div className="gantt" data-testid="plan-gantt">
        <div className="gantt-row gantt-head" aria-hidden="true">
          <span className="gantt-label" />
          <div className="gantt-days">
            {days.map((day) => (
              <span className="gantt-day muted small" key={day.date}>
                <span>{day.weekday}</span>
                <span>{day.date}</span>
              </span>
            ))}
          </div>
        </div>
        {rows.map((task) => {
          const shift = shifts.get(task.id);
          return (
            <div
              className="gantt-row"
              key={task.id}
              data-testid="plan-task"
              data-task-id={task.id}
              data-status={task.status ?? "planned"}
              data-shifted={shift ? "true" : "false"}
            >
              <div className="gantt-label">
                <span className="row">
                  <strong title={task.name}>{workName(task.name, task)}</strong>
                  {task.status === "on_hold" && <Badge tone="warning">On hold</Badge>}
                  {shift && <Badge tone="accent">{shiftLabel(shift)}</Badge>}
                </span>
                <span className="muted small">{task.crew} · {locationLabel(task.unit)}</span>
              </div>
              <div className="gantt-track">
                <div
                  className={`gantt-bar gantt-bar-original${task.status === "on_hold" ? " gantt-bar-hold" : ""}`}
                  style={barStyle(task.start, task.end, weekStart)}
                  title={`${formatTime(task.start)} to ${formatTime(task.end)}`}
                />
                {shift && (
                  <div
                    className="gantt-bar gantt-bar-proposed"
                    data-testid="plan-task-proposed"
                    style={barStyle(shift.new_start, shift.new_end, weekStart)}
                    title={`Proposed: ${formatTime(shift.new_start)} to ${formatTime(shift.new_end)}`}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
      {inWeek.length > CHART_ROWS && (
        <button type="button" className="button plan-more" data-testid="plan-gantt-toggle" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show fewer tasks" : `Show all ${inWeek.length} tasks this week`}
        </button>
      )}
    </>
  );
}

const BASIS_TEXT: Record<Proposal["basis"], string> = {
  calculated: "Calculated from schedule dependencies",
  rule: "From a fixed rule, not a forecast",
  assistant: "Suggested from a typed instruction",
};

interface CardProps {
  proposal: Proposal;
  flag?: Flag;
  tasks: Task[];
  weekStart: number;
  shiftedIds: Set<string>;
  onDecided: () => void;
}

function ProposalCard({ proposal, flag, tasks, weekStart, shiftedIds, onDecided }: CardProps) {
  const location = useLocation();
  const card = useRef<HTMLElement>(null);
  const selected = new URLSearchParams(location.search).get("proposal") === proposal.id || location.hash === `#proposal-${proposal.id}`;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shifts = proposal.shifts ?? [];
  const summary = proposalSummary(proposal);
  const moves =
    proposal.handover_old && proposal.handover_new && proposal.handover_old !== proposal.handover_new;
  const untouched = tasks
    .filter((task) => overlapsWeek(task, weekStart) && !shiftedIds.has(task.id))
    .sort((a, b) => a.start.localeCompare(b.start) || a.id.localeCompare(b.id))
    .slice(0, NOT_AFFECTED_ROWS);

  useEffect(() => {
    if (selected) card.current?.scrollIntoView({ block: "start" });
  }, [selected]);

  async function accept() {
    if (!proposal.flag_id) return;
    setBusy(true);
    setError(null);
    try {
      await api.decide({ flag_id: proposal.flag_id, action: proposal.action, proposal_id: proposal.id });
      onDecided();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The decision was not saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section ref={card} id={`proposal-${proposal.id}`} className={`panel plan-proposal${selected ? " plan-proposal-selected" : ""}`} data-testid="plan-proposal" data-proposal-id={proposal.id} aria-labelledby={`proposal-title-${proposal.id}`}>
      <div className="stack">
        <h2 id={`proposal-title-${proposal.id}`}>Proposed downstream impact</h2>
        <Badge tone="warning">Awaiting human approval</Badge>
        {summary && (
          <p className="plan-proposal-summary" data-testid="plan-proposal-summary">
            {summary}
          </p>
        )}
        {flag && <>
          <Link to={`/flags/${flag.id}`}>{flag.title}: view report and sources</Link>
          {flag.evidence?.[0] && <p className="muted small">{flag.evidence[0].sender}: “{flag.evidence[0].quote}”</p>}
        </>}
        <p className="muted small">These dates have not changed the accepted schedule.</p>
        <p className="muted small">{BASIS_TEXT[proposal.basis]}</p>
      </div>

      {moves ? (
        <div className="plan-handover-pair">
          <div className="plan-handover-box" data-testid="plan-handover-old">
            <span className="small">Handover now</span>
            <strong className="plan-handover-date">{formatDay(proposal.handover_old)}</strong>
          </div>
          <div className="plan-handover-box plan-handover-new" data-testid="plan-handover-new">
            <span className="small">Handover proposed</span>
            <strong className="plan-handover-date">{formatDay(proposal.handover_new)}</strong>
          </div>
        </div>
      ) : (
        proposal.handover_old && <p className="muted small">Handover stays {formatDay(proposal.handover_old)}.</p>
      )}

      <p>{proposal.summary}</p>

      {shifts.length > 0 && (
        <div className="stack">
          <h3>If this change is accepted</h3>
          <ol className="plan-chain" data-testid="plan-chain">
            {shifts.map((shift) => (
              <li key={shift.task_id}>
                <span className="plan-chain-name">
                  {workName(shift.name, tasks.find((task) => task.id === shift.task_id))}
                  <span className="muted small">Crew: {shift.crew}</span>
                  <span className="small">Planned: {formatRange(shift.old_start, shift.old_end)}</span>
                  <span className="small">Proposed: {formatRange(shift.new_start, shift.new_end)}</span>
                </span>
                <span className="plan-chain-delta num">{shiftLabel(shift)}</span>
              </li>
            ))}
            {moves && (
              <li className="plan-chain-end">
                <span className="plan-chain-name">Handover</span>
                <span className="plan-chain-delta num">
                  {formatDay(proposal.handover_new)}
                  <span className="muted small">{moveLabel(proposal.handover_old as string, proposal.handover_new as string)}</span>
                </span>
              </li>
            )}
          </ol>
        </div>
      )}

      {untouched.length > 0 && (
        <div className="stack">
          <h3>No proposed date change</h3>
          <ul className="plan-unchanged" data-testid="plan-unchanged">
            {untouched.map((task) => (
              <li key={task.id}>
                <span>{workName(task.name, task)}</span>
                <span className="muted small">No change</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p className="plan-error" role="alert" data-testid="plan-decision-error">
          {error}
        </p>
      )}
      <div className="row">
        {proposal.flag_id && (
          <button type="button" className="button button-primary" data-testid="plan-accept" disabled={busy} onClick={accept}>
            {busy ? "Saving" : actionLabel(proposal.action)}
          </button>
        )}
        {proposal.flag_id && (
          <Link className="button" to={`/flags/${proposal.flag_id}`} data-testid="plan-open-flag">
            Open flag
          </Link>
        )}
      </div>
    </section>
  );
}

function countTone(difference: number): string {
  return difference === 0 ? "none" : difference > 0 ? "over" : "under";
}

function ResourceRow({ line, flags }: { line: ResourceLine; flags: Flag[] }) {
  const unit = line.unit && line.unit !== "count" ? ` ${line.unit}` : "";
  const cell = actualFor(line, flags);
  const tone =
    cell.source === "unavailable"
      ? "unknown"
      : cell.source === "reported" && cell.kind === "day"
        ? cell.late
          ? "over"
          : "none"
        : countTone(cell.difference);

  let actual: ReactNode;
  let difference: ReactNode;
  if (cell.source === "reported") {
    actual = (
      <span className="plan-actual" data-testid="plan-actual-reported" data-flag-id={cell.flagId}>
        <span>
          {cell.kind === "count" ? (
            <>
              {formatNumber(cell.value)}
              {unit}
            </>
          ) : (
            <span title={cell.day}>{formatTime(cell.day)}</span>
          )}
        </span>
        <Link className="plan-actual-mark small" to={`/flags/${cell.flagId}`} title={cell.flagTitle}>
          {cell.kind === "day" ? "Reported arrival · source" : "Reported quantity · source"}
        </Link>
      </span>
    );
    difference =
      cell.kind === "day" ? (
        cell.move === "no change" ? (
          <span className="plan-diff plan-diff-none">as planned</span>
        ) : (
          <span className={`plan-diff plan-diff-${tone}`}>{cell.move}</span>
        )
      ) : cell.difference === 0 ? (
        <span className="plan-diff plan-diff-none">as planned</span>
      ) : (
        <span className={`plan-diff plan-diff-${tone}`}>
          {formatSigned(cell.difference)}
          {unit}
        </span>
      );
  } else if (cell.source === "plan") {
    actual = (
      <span className="plan-actual">
        <span>
        {formatNumber(cell.value)}
        {unit}
        </span>
        <span className="muted small">Recorded actual quantity</span>
      </span>
    );
    difference =
      cell.difference === 0 ? (
        <span className="plan-diff plan-diff-none">as planned</span>
      ) : (
        <span className={`plan-diff plan-diff-${tone}`}>
          {formatSigned(cell.difference)}
          {unit}
        </span>
      );
  } else {
    actual = cell.flagId ? (
      <span className="plan-actual">
        <span className="muted">{cell.dismissed ? "Report dismissed" : "No arrival or quantity in report"}</span>
        <Link className="plan-actual-mark small" to={`/flags/${cell.flagId}`} title={cell.flagTitle ?? undefined}>
          {cell.dismissed ? "report dismissed" : "see flag"}
        </Link>
      </span>
    ) : (
      <span className="muted">No report received</span>
    );
    difference = <span className="muted small">No reported change</span>;
  }

  return (
    <li className="plan-resource" data-testid="plan-resource-row" data-difference={tone} data-actual={cell.source}>
      <div className="plan-resource-head">
        <span className="plan-item">
          <span className={`plan-marker plan-marker-${tone}`} aria-hidden="true" />
          <strong>{line.item}</strong>
        </span>
        <span className="muted small">{line.kind === "delivery" ? "Delivery / truck arrival" : line.kind === "equipment" ? "Equipment" : "Crew"}</span>
      </div>
      <dl className="plan-resource-facts">
        <div><dt>{line.kind === "delivery" ? "Planned arrival" : "Planned availability"} (UTC)</dt><dd title={line.date}>{formatTime(line.date)}</dd><dd className="small muted">Planned quantity: {formatNumber(line.planned)}{unit}</dd></div>
        <div><dt>Latest report / recorded actual</dt><dd>{actual}</dd></div>
      </dl>
      <div className="plan-resource-difference"><span className="muted small">Difference from plan</span>{difference}</div>
    </li>
  );
}
