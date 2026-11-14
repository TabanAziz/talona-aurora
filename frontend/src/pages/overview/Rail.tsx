import type { Flag, Plan, RecordEntry, WaitingItem } from "../../api/client";
import type { Query } from "../../api/useQuery";
import { formatDay, formatTime } from "../../components/format";
import { Async } from "../../components/States";
import { Icon } from "./icons";
import { clock, confirmedToday, distance, nextSiteDay, openWaiting, riskyTasks, span } from "./logic";
import { StartChecks } from "./Autonomy";
import { Link } from "react-router-dom";
import { workName } from "../plan/presentation";

interface Props {
  waiting: Query<WaitingItem[]>;
  record: Query<RecordEntry[]>;
  plan: Query<Plan>;
  flags: Flag[];
  now: number | null;
}

/** How long until an answer is due, counted from the demo's "now"; late answers say so. */
function dueLabel(due: string | null | undefined, now: number | null): string | null {
  const delta = distance(due, now);
  if (delta === null) return null;
  return delta >= 0 ? span(delta) : `${span(-delta)} late`;
}

export function Rail({ waiting, record, plan, flags, now }: Props) {
  const risky = riskyTasks(flags);
  return (
    <div className="today-rail">
      <section className="panel" aria-labelledby="waiting-heading">
        <div className="panel-head">
          <h2 id="waiting-heading">Waiting for a reply</h2>
          <span className="panel-aside">{waiting.data ? `${openWaiting(waiting.data).length} open` : ""}</span>
        </div>
        <Async query={waiting} rows={2} empty="Nobody owes an answer right now.">
          {(items) => (
            <ul className="rail-list" data-testid="waiting-list">
              {openWaiting(items).map((item) => (
                <li key={item.id} className="rail-item" data-testid="waiting-item">
                  <span className="rail-lead">
                    <Icon name="clock" />
                  </span>
                  <span className="rail-main">
                    <Link to="/crew"><strong>{item.what}</strong></Link>
                    <span className="muted">{item.on}</span>
                  </span>
                  <span className="rail-end num muted" title={formatTime(item.due)}>
                    {dueLabel(item.due, now)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Async>
      </section>

      <div className="overview-support"><StartChecks /><section className="panel" aria-labelledby="confirmed-heading">
        <div className="panel-head">
          <h2 id="confirmed-heading">Confirmed today</h2>
          <span className="panel-aside">{record.data ? `${confirmedToday(record.data, now).length} closed` : ""}</span>
        </div>
        <Async query={record} rows={2}>
          {(entries) => {
            const items = confirmedToday(entries, now);
            if (items.length === 0) return <p className="muted" data-testid="confirmed-empty">Nothing is confirmed yet today.</p>;
            return (
              <ul className="rail-list" data-testid="confirmed-list">
                {items.map((entry) => (
                  <li key={entry.id} className="rail-item" data-testid="confirmed-item">
                    <span className="rail-lead rail-lead-success">
                      <Icon name="check" />
                    </span>
                    <span className="rail-main">
                      <strong>{entry.title}</strong>
                      <span className="muted">{entry.actor ?? "unavailable"}</span>
                    </span>
                    <span className="rail-end num muted">{clock(entry.at)}</span>
                  </li>
                ))}
              </ul>
            );
          }}
        </Async>
      </section>

      <SiteDay plan={plan} now={now} risky={risky} />
      </div>
    </div>
  );
}

function SiteDay({ plan, now, risky }: { plan: Query<Plan>; now: number | null; risky: Set<string> }) {
  const next = plan.data ? nextSiteDay(plan.data.tasks ?? [], now) : null;
  return (
    <section className="panel" aria-labelledby="site-heading">
      <div className="panel-head">
        <h2 id="site-heading">{next && !next.tomorrow ? "Next on site" : "Tomorrow on site"}</h2>
        <span className="panel-aside">{next ? formatDay(next.day) : ""}</span>
      </div>
      <Async query={plan} rows={3}>
        {() =>
          next === null ? (
            <p className="muted" data-testid="site-empty">Nothing is scheduled after the latest event.</p>
          ) : (
            <><ul className="rail-list" data-testid="site-list">
              {next.tasks.slice(0, 6).map((task) => (
                <li key={task.id} className="rail-item" data-testid="site-item">
                  <span className="rail-time num">{clock(task.start)}</span>
                  <span className="rail-main">
                    <Link to="/plan"><strong>{workName(task.name, task)}</strong></Link>
                    <span className="muted">{task.crew}</span>
                  </span>
                  <span className="rail-end">
                    {task.status === "on_hold" ? (
                      <span className="status status-warning">On hold</span>
                    ) : risky.has(task.id) ? (
                      <span className="status status-danger">At risk</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul><Link className="overview-full-schedule" to="/plan">View full schedule{next.tasks.length > 6 ? ` · ${next.tasks.length - 6} more tasks` : ""} <span aria-hidden="true">↗</span></Link></>
          )
        }
      </Async>
    </section>
  );
}
