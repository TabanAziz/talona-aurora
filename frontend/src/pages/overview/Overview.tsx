import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Flag, type Plan, type RecordEntry, type WaitingItem } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { FlagStatusBadge, FlagTypeBadge } from "../../components/Badge";
import { Async } from "../../components/States";
import { formatTime } from "../../components/format";
import { FlagFocus } from "./FlagFocus";
import { Rail } from "./Rail";
import { RecordColumn } from "./RecordColumn";
import { SiteStill } from "./SiteStill";
import { referenceTime, sortFlags } from "./logic";
import { Autonomy } from "./Autonomy";
import { Activity } from "./Activity";
import "./overview.css";

const POLL_MS = 3000;
const EMPTY_PLAN: Plan = { handover: "", tasks: [], resources: [] };

export function Overview() {
  const record = useQuery(api.record, [], { poll: POLL_MS, empty: [] as RecordEntry[] });
  const waiting = useQuery(api.waiting, [], { poll: POLL_MS, empty: [] as WaitingItem[] });
  const flags = useQuery(api.flags, [], { poll: POLL_MS, empty: [] as Flag[] });
  const plan = useQuery(api.plan, [], { poll: POLL_MS, empty: EMPTY_PLAN });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [siteOpen, setSiteOpen] = useState(true);

  const sorted = sortFlags(flags.data ?? []);
  const open = sorted.filter(flag => flag.status === "open" || flag.status === undefined);
  const selected = open[0] ?? sorted.find(flag => flag.status === "held");
  const now = referenceTime(record.data ?? [], flags.data ?? []);

  async function run(action: "next" | "reset") {
    setBusy(true);
    setNotice(null);
    try {
      if (action === "next") {
        const result = await api.demoNext();
        if (result === null) setNotice("Every event of the demo was played.");
      } else {
        await api.demoReset();
      }
      record.reload();
      waiting.reload();
      flags.reload();
      plan.reload();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "The demo control failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Overview</h1><p className="muted">The latest site updates and what needs your attention.</p></div>
        <details className="overview-controls"><summary>Scenario controls</summary><div className="row">
          {notice && (
            <span className="muted small" role="status" data-testid="demo-notice">
              {notice}
            </span>
          )}
          <button type="button" className="button" data-testid="demo-reset" disabled={busy} onClick={() => run("reset")}>
            Reset scenario
          </button>
          <button
            type="button"
            className="button button-primary"
            data-testid="demo-next"
            disabled={busy}
            onClick={() => run("next")}
          >
            Play next event
          </button>
        </div></details>
      </div>

      <Activity />
      <nav className="overview-shortcuts" aria-label="Project workspaces">
        <Link to="/site">Building & live site</Link>
        <Link to="/drawings">Drawings & revisions</Link>
        <Link to="/daily">Daily report</Link>
        <Link to="/machines">Equipment</Link>
        <Link to="/instructions">Give an instruction</Link>
        <Link to="/timelapse">Project timeline</Link>
      </nav>

      <div className="today">
        <section className="today-focus" aria-label="Flags">
          <div className="overview-section-head"><h2>{open.length ? "Needs your decision" : "Site decisions"}</h2><span className="muted">{open.length} open</span></div>
          <Async query={flags} rows={2} empty="No issues need your decision. Aurora is watching for changes that affect the work.">
            {() => (
              <>
                {selected && <FlagFocus key={selected.id} flag={selected} now={now} />}
                {!selected && <p className="overview-clear muted">Nothing needs a decision right now.</p>}
                <details className="overview-issues" open>
                  <summary>All issues <span className="muted">{sorted.length} recorded</span></summary>
                  <div className="flag-row">
                    <ul className="flag-cards" data-testid="flags-list">
                      {sorted.map((flag) => (
                        <li key={flag.id}>
                          <Link
                            className="flag-card"
                            to={`/flags/${flag.id}`}
                            data-testid="flag-card"
                            data-flag-id={flag.id}
                            aria-current={flag === selected ? "true" : undefined}
                          >
                            <span className="row">
                              <FlagTypeBadge type={flag.type} />
                              <FlagStatusBadge status={flag.status} />
                            </span>
                            <span className="flag-card-title">{flag.title}</span>
                            <span className="muted small" title={flag.work_starts_at ?? undefined}>
                              Work starts {formatTime(flag.work_starts_at)}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                </details>
              </>
            )}
          </Async>
        </section>

        <Rail waiting={waiting} record={record} plan={plan} flags={flags.data ?? []} now={now} />
      </div>
      <div className="overview-secondary">
        <RecordColumn record={record} selected={selected} now={now} />
        <details className="overview-site-context" open onToggle={event => setSiteOpen(event.currentTarget.open)}><summary>Building & live site <Link to="/site">Open full view ↗</Link></summary>{siteOpen && <SiteStill flags={flags.data ?? []} waiting={waiting.data ?? []} plan={plan.data ?? EMPTY_PLAN} />}</details>
      </div>
      <Autonomy />
    </>
  );
}
