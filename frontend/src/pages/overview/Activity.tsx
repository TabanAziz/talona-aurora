import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../../api/client";
import { useForcedState } from "../../api/useQuery";
import { formatTime, humanize } from "../../components/format";
import { Icon, type IconName } from "./icons";

type StageState = "pending" | "processing" | "completed" | "waiting" | "failed" | "skipped";

// Live status keeps its last result and its failed refresh visible together.
function useLiveStatus<T>(fetcher: () => Promise<T>, poll: number, empty: T) {
  const forced = useForcedState();
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (forced) return;
    let cancelled = false;
    let inFlight = false;
    async function load() {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await fetcher();
        if (cancelled) return;
        setData(result);
        setError(null);
        setCheckedAt(new Date().toISOString());
      } catch {
        if (!cancelled) setError("The live service did not answer.");
      } finally {
        inFlight = false;
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), poll);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [fetcher, poll, tick, forced]);
  const reload = () => setTick(value => value + 1);
  if (forced === "loading") return { data: undefined, error: null, checkedAt: null, loading: true, reload };
  if (forced === "empty") return { data: empty, error: null, checkedAt: null, loading: false, reload };
  if (forced === "error") return { data: undefined, error: "The live service did not answer.", checkedAt: null, loading: false, reload };
  return { data, error, checkedAt, loading: loading && data === undefined, reload };
}
interface ActivityJob {
  id: string;
  event_id: string;
  channel: string;
  sender: string;
  subject: string;
  status: "queued" | "processing" | "completed" | "failed";
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  stage: string | null;
  stages: { id: string; label: string; status: StageState }[];
  result: { flag_ids: string[]; diff_ids: string[]; message_ids: string[]; record_ids: string[]; outcome?: string; delivery_failed_ids?: string[]; delivery_queued_ids?: string[]; delivery_simulated_ids?: string[] };
  error?: string;
}

const readActivity = () => request<{ jobs: ActivityJob[] }>("GET", "/api/activity");
const EMPTY_ACTIVITY = { jobs: [] as ActivityJob[] };

function stateLabel(job: ActivityJob): string {
  if (job.result.outcome === "awaiting_confirmation") return "Waiting for confirmation";
  return { queued: "Queued", processing: "Processing", completed: "Processed", failed: "Needs attention" }[job.status];
}

function ResultLinks({ job }: { job: ActivityJob }) {
  const result = job.result;
  const conversation = `/crew?event=${encodeURIComponent(job.event_id)}`;
  return (
    <div className="activity-results">
      {result.flag_ids.map((id, index) => <Link className="activity-result-primary" key={id} to={`/flags/${encodeURIComponent(id)}`}><Icon name="flag" />Review issue{result.flag_ids.length > 1 ? ` ${index + 1}` : ""}<span aria-hidden="true">↗</span></Link>)}
      {result.diff_ids.map((id, index) => <Link key={id} to={`/compare/${encodeURIComponent(id)}`}><Icon name="change" />Drawing change{result.diff_ids.length > 1 ? ` ${index + 1}` : ""}<span aria-hidden="true">↗</span></Link>)}
      {job.stages.some(stage => stage.id === "rules" && stage.status === "completed") && <Link to="/plan"><Icon name="clock" />Review schedule<span aria-hidden="true">↗</span></Link>}
      <Link className={result.outcome === "awaiting_confirmation" ? "activity-result-primary" : undefined} to={conversation}><Icon name="chat" />{result.outcome === "awaiting_confirmation" ? "Confirm in conversation" : result.message_ids.length ? "View conversation & updates" : "Open source message"}<span aria-hidden="true">↗</span></Link>
      {result.record_ids.length > 0 && !result.diff_ids.length && !result.flag_ids.length && <Link to={`/#record-${encodeURIComponent(result.record_ids[0])}`}><Icon name="decision" />View recorded result<span aria-hidden="true">↓</span></Link>}
      {!!result.delivery_failed_ids?.length && <span className="activity-error">{result.delivery_failed_ids.length} crew updates could not be delivered</span>}
      {!!result.delivery_queued_ids?.length && <span className="muted">{result.delivery_queued_ids.length} crew updates queued</span>}
      {!!result.delivery_simulated_ids?.length && <span className="muted">{result.delivery_simulated_ids.length} crew updates simulated</span>}
    </div>
  );
}

function outcomeSummary(job: ActivityJob): string {
  if (job.result.outcome === "awaiting_confirmation") return "A voice transcript is ready and needs the sender's confirmation.";
  if (job.status === "failed") return job.error || "Processing stopped. Open the source conversation to follow up.";
  if (job.status === "processing") return job.stages.find(stage => stage.status === "processing")?.label || "Processing this site update.";
  if (job.status === "queued") return "This update is queued for processing.";
  const result = job.result;
  const parts = [result.flag_ids.length ? `${result.flag_ids.length} issue${result.flag_ids.length === 1 ? "" : "s"} raised` : "", result.diff_ids.length ? `${result.diff_ids.length} drawing change${result.diff_ids.length === 1 ? "" : "s"} found` : "", result.message_ids.length ? `${result.message_ids.length} crew update${result.message_ids.length === 1 ? "" : "s"} prepared` : "", result.record_ids.length ? `${result.record_ids.length} record entr${result.record_ids.length === 1 ? "y" : "ies"} added` : ""].filter(Boolean);
  return parts.length ? `${parts.join(" · ")}.` : job.result.outcome === "handled_readback" ? "Voice confirmation handled. Open the conversation for the recorded response." : "Processing finished. Open the source conversation to review the result.";
}

function StageFlow({ stages, stale }: { stages: ActivityJob["stages"]; stale: boolean }) {
  return <ol className="activity-flow" aria-label="Processing stages">
    {stages.map(stage => <li key={stage.id} data-stage-state={stage.status} className={`activity-stage activity-stage-${stage.status}`}>
      <span className="activity-stage-mark" aria-hidden="true">{stage.status === "completed" ? <Icon name="check" /> : stage.status === "failed" ? "!" : <span />}</span>
      <span>{stage.label}<span className="activity-stage-status">{stage.status === "processing" ? stale ? "Last known active" : "In progress" : stage.status === "waiting" ? "Needs your reply" : stage.status === "failed" ? "Failed" : stage.status === "skipped" ? "Not needed" : stage.status === "completed" ? "Done" : "Next"}</span></span>
    </li>)}
  </ol>;
}

function Job({ job, current = false, arrived = false, stale = false }: { job: ActivityJob; current?: boolean; arrived?: boolean; stale?: boolean }) {
  const waiting = job.result.outcome === "awaiting_confirmation";
  const icon: IconName = waiting ? "chat" : job.status === "failed" || job.result.flag_ids.length ? "flag" : job.result.diff_ids.length ? "change" : job.status === "completed" ? "check" : "clock";
  return (
    <article className={`activity-job${arrived ? " activity-arrived" : ""}`} data-testid={current ? "activity-current" : "activity-job"} data-status={waiting ? "waiting" : job.status}>
      <div className="activity-job-kind"><span className="activity-job-icon"><Icon name={icon} /></span><span>{current ? job.status === "processing" ? "In progress" : waiting ? "Your attention" : "Latest update" : "Recorded update"}</span></div>
      <div className="activity-job-head">
        <div className="activity-source"><span>{humanize(job.channel)}</span><span className="muted">from {job.sender}</span></div>
        <span className={`activity-state activity-state-${waiting ? "waiting" : job.status}`}><span className="activity-state-dot" aria-hidden="true" />{stale ? `Last known: ${stateLabel(job).toLowerCase()}` : stateLabel(job)}</span>
      </div>
      <h3>{job.subject || "New site message"}</h3>
      <p className={`activity-outcome${job.status === "failed" ? " activity-error" : ""}`}>{outcomeSummary(job)}</p>
      {current && (job.status === "completed" ? <details key={job.id} className="activity-processing-details" data-testid="activity-processing-details"><summary>Processing details <span className="muted">{job.stages.length} stages</span></summary><StageFlow stages={job.stages} stale={stale} /></details> : <StageFlow stages={job.stages} stale={stale} />)}
      <div className="activity-job-foot"><ResultLinks job={job} />
      <p className="activity-timestamp muted">{job.finished_at ? "Finished" : "Updated"} <time dateTime={job.finished_at ?? job.updated_at} title={job.finished_at ?? job.updated_at}>{formatTime(job.finished_at ?? job.updated_at)}</time></p>
      </div>
    </article>
  );
}

export function Activity() {
  const activity = useLiveStatus(readActivity, 1200, EMPTY_ACTIVITY);
  const seen = useRef<Set<string> | null>(null);
  const [arrived, setArrived] = useState<Set<string>>(new Set());
  const jobs = [...(activity.data?.jobs ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const active = jobs.filter(job => job.status === "queued" || job.status === "processing");
  const current = active.find(job => job.status === "processing") ?? active[0] ?? jobs[0];
  const others = jobs.filter(job => job.id !== current?.id);
  const attention = jobs.filter(job => job.status === "failed" || job.result.outcome === "awaiting_confirmation").length;
  const completed = jobs.filter(job => job.status === "completed").length;
  useEffect(() => {
    if (!activity.data) return;
    const ids = new Set(activity.data.jobs.map(job => job.id));
    if (seen.current) setArrived(new Set([...ids].filter(id => !seen.current?.has(id))));
    seen.current = ids;
  }, [activity.data]);
  return (
    <section className="activity" data-testid="overview-activity" data-stale={Boolean(activity.error)} aria-labelledby="activity-heading">
      <div className="activity-heading"><div><p className="overview-eyebrow">Aurora at work</p><h2 id="activity-heading">{activity.error && activity.data ? "Last known activity" : "Project activity"}</h2><p className="activity-intro muted">Follow each site update from its source to the next action.</p></div><span className="activity-listening"><span aria-hidden="true" />{activity.error ? "Live updates unavailable" : activity.loading ? "Connecting" : active.length ? `${active.length} open updates` : "Listening for updates"}</span></div>
      {jobs.length > 0 && <div className="activity-snapshot" aria-label="Activity recorded in this service session"><span className="activity-snapshot-label">This session{activity.error ? " · last known" : ""}</span><span><strong>{active.length}</strong> open</span><span data-attention={attention > 0}><strong>{attention}</strong> need attention</span><span><strong>{completed}</strong> processed</span></div>}
      {activity.error && activity.data && <div className="activity-stale" data-testid="activity-stale" role="status"><Icon name="info" /><div><strong>Live activity is temporarily unavailable</strong><p>Showing the last known result. Last successful refresh: <time dateTime={activity.checkedAt ?? undefined}>{formatTime(activity.checkedAt)}</time>.</p></div><button className="button" data-testid="activity-retry" onClick={activity.reload}>Retry live updates</button></div>}
      <div className="activity-content" aria-live="polite" aria-atomic="false">
        {activity.error && !activity.data ? <div className="activity-empty"><Icon name="info" /><div><h3>Activity is unavailable</h3><p className="muted">The activity service did not answer. Your project record is still below.</p><button className="button" onClick={activity.reload}>Try again</button></div></div>
          : activity.loading ? <div className="activity-empty"><span className="activity-stage-mark activity-loading" aria-hidden="true" /><div><h3>Connecting to project activity</h3><p className="muted">Reading the latest processing state.</p></div></div>
          : current ? <Job job={current} current arrived={arrived.has(current.id)} stale={Boolean(activity.error)} />
          : <div className="activity-empty"><span className="activity-idle" aria-hidden="true"><Icon name="check" /></span><div><h3>{activity.error ? "No activity in the last received state" : "Ready for the next site update"}</h3><p className="muted">{activity.error ? "Live updates will resume when the service answers again." : "New messages, drawing checks and their results will appear here as Aurora processes them."}</p><Link className="activity-empty-action" to="/crew">Open project messages <span aria-hidden="true">↗</span></Link></div></div>}
      </div>
      {others.length > 0 && <div className="activity-recent"><div className="activity-recent-heading"><h3>Recent updates</h3><span className="muted small">{others.length} recorded</span></div><ol className="activity-timeline">{others.slice(0, 3).map(job => <li key={job.id}><Job job={job} stale={Boolean(activity.error)} /></li>)}</ol>{others.length > 3 && <details className="activity-history"><summary>Earlier updates <span className="muted">{others.length - 3} recorded</span></summary><ol className="activity-timeline">{others.slice(3, 15).map(job => <li key={job.id}><Job job={job} stale={Boolean(activity.error)} /></li>)}</ol>{others.length > 15 && <Link to="/timelapse">Open project timeline for older results ↗</Link>}</details>}</div>}
    </section>
  );
}
