import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type DecisionRequest, type DrawingDiff, type Flag, type Proposal } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge, FlagStatusBadge } from "../../components/Badge";
import { proposalSummary } from "../../components/proposalSummary";
import { actionLabel, formatDay, formatNumber, formatRange, formatTime, humanize } from "../../components/format";
import { Async, Empty, ErrorState, Loading } from "../../components/States";
import { askerKind, stoppedChecks, stoppedCrews } from "./stopped";
import "./flag.css";

export function FlagDetail() {
  const { id = "" } = useParams();
  return <FlagPage key={id} id={id} />;
}

function FlagPage({ id }: { id: string }) {
  const forced = useForcedState();
  const flag = useQuery(() => api.flag(id), [id], { poll: 5000, skip: forced === "empty" });

  return (
    <>
      {(forced || flag.loading || flag.error) && <Link className="back-link" to="/">
        Back to Today
      </Link>}
      {forced === "empty" ? <Empty>No flag selected. <Link to="/">View the live record</Link>.</Empty> : <Async query={flag} rows={4}>
        {(data) => <FlagBody flag={data} onChanged={flag.reload} />}
      </Async>}
    </>
  );
}

function FlagBody({ flag, onChanged }: { flag: Flag; onChanged: () => void }) {
  // The proposal is looked up by flag, because a flag can exist before its proposal id is written back.
  const proposals = useQuery(api.proposals, [flag.id, flag.status], { poll: 5000 });
  const diff = useQuery(() => api.diff(flag.diff_id ?? ""), [flag.diff_id], { skip: !flag.diff_id });
  const decisions = useQuery(api.decisions, [flag.id, flag.status], { poll: 5000 });
  const outbox = useQuery(api.outbox, [flag.id, flag.status], { poll: 5000 });
  const record = useQuery(api.record, [flag.id, flag.status], { poll: 5000 });
  const waiting = useQuery(api.waiting, [flag.id, flag.status], { poll: 5000 });
  const checks = useQuery(api.checks, [flag.id, flag.status], { poll: 5000 });
  // A hold Aurora made under a grant: the decision names the authorization, and the grant says who gave it.
  const autoHold = (decisions.data ?? []).find(
    (decision) => decision.flag_id === flag.id && decision.authorization_id && decision.decided_by === "Aurora",
  );
  const autonomy = useQuery(api.autonomy, [autoHold?.authorization_id ?? ""], { skip: !autoHold });
  const authorization = (autonomy.data?.authorizations ?? []).find((item) => item.id === autoHold?.authorization_id);
  const [standingRule, setStandingRule] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const proposal: Proposal | undefined = proposals.data?.find(
    (p) => p.id === flag.proposal_id && p.flag_id === flag.id,
  ) ?? proposals.data?.find((p) => p.flag_id === flag.id && p.status === "proposed");
  const status = flag.status ?? "open";
  const history = (decisions.data ?? []).filter((d) => d.flag_id === flag.id).sort((a, b) => b.decided_at.localeCompare(a.decided_at));
  const decisionIds = new Set(history.map((decision) => decision.id));
  const messageIds = new Set((record.data ?? []).filter((entry) =>
    entry.kind === "notice" && entry.refs?.flag === flag.id && decisionIds.has(entry.refs?.decision ?? ""),
  ).map((entry) => entry.refs?.message));
  const messages = (outbox.data ?? []).filter((message) => messageIds.has(message.id));
  const stopped = stoppedCrews(waiting.data ?? [], flag.affected ?? {});
  const refusals = stoppedChecks(checks.data ?? [], flag.affected ?? {});

  async function decide(action: DecisionRequest["action"], proposalId: string | null) {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await api.decide({ flag_id: flag.id, action, proposal_id: proposalId, standing_rule: standingRule });
      onChanged();
      decisions.reload();
      outbox.reload();
      record.reload();
      proposals.reload();
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : "The decision was not saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="flag-detail" data-testid="flag-detail" aria-busy={busy}>
      <header className="stack">
        <div className="flag-topline">
          <div className="row"><Link className="flag-back" to="/">Today</Link><span className="flag-type">{humanize(flag.type)}</span></div>
          <div className="row">
          <FlagStatusBadge status={status} testId="flag-status" />
          <span className="muted small num" title={flag.raised_at}>
            Flagged {formatTime(flag.raised_at)}
          </span>
          </div>
        </div>
        <h1 data-testid="flag-title">{flag.title}</h1>
        <p className="flag-start"><strong>Work starts</strong> <time className="num" dateTime={flag.work_starts_at ?? undefined}>{formatTime(flag.work_starts_at)}</time></p>
        <p className="flag-summary muted">{flag.summary}</p>
      </header>

      {status === "held" && autoHold && (
        <section className="section flag-auto" data-testid="flag-auto-held" aria-labelledby="flag-auto-heading">
          <h2 id="flag-auto-heading">Automatic hold</h2>
          <p>
            {authorization
              ? <>Held by Aurora under the authorization of <strong>{authorization.granted_by}</strong>.</>
              : <>Held by Aurora under an authorization.</>}
          </p>
          {authorization && <p className="muted small">{authorization.statement}</p>}
          <div className="row">
            <Link className="flag-auto-link" to="/autonomy" data-testid="flag-auto-link">See the authorization</Link>
            <button type="button" className="button" data-testid="flag-undo" disabled={busy} onClick={() => decide("release_work", null)}>
              Undo this hold
            </button>
          </div>
        </section>
      )}

      {flag.diff_id && <section aria-label="Drawing change">
        {diff.error ? <ErrorState message={diff.error} onRetry={diff.reload} /> : diff.loading ? <Loading rows={3} label="Loading drawing change" /> :
          diff.data && <DrawingChange key={diff.data.id} diff={diff.data} flag={flag} />}
      </section>}

      <div className={`flag-columns${!flag.diff_id && (proposal?.shifts?.length ?? 0) > 0 ? " flag-columns-plan" : ""}`}>
        <section className="section" aria-labelledby="evidence-heading">
          <h2 id="evidence-heading">Sources</h2>
          {(flag.evidence ?? []).length === 0 && <Empty>Source evidence is unavailable.</Empty>}
          <ul className="flag-evidence" data-testid="flag-evidence">
            {(flag.evidence ?? []).map((item) => (
              <li className="flag-source" key={`${item.event_id}-${item.at}`} data-testid="evidence-item">
                <div className="flag-source-heading">
                  <span><strong>{humanize(item.channel)}</strong> from {item.sender || "unavailable"}</span>
                  <span className="muted small num" title={item.at}>
                    {formatTime(item.at)}
                  </span>
                </div>
                <blockquote className="flag-quote"><HighlightedQuote quote={item.quote} flag={flag} diff={diff.data} /></blockquote>
                {item.attachment_url && <a className="flag-source-link" href={item.attachment_url} target="_blank" rel="noreferrer">Open source attachment</a>}
              </li>
            ))}
          </ul>

          {flag.numbers && Object.keys(flag.numbers).length > 0 && (
            <dl className="flag-numbers" data-testid="flag-numbers">
              {Object.entries(flag.numbers).map(([key, value]) => (
                <div className="flag-number" key={key}>
                  <dt className="muted small">{humanize(key)}</dt>
                  <dd className="num">{formatNumber(value)}</dd>
                </div>
              ))}
            </dl>
          )}
          <div className="flag-stopped" data-testid="flag-stopped" aria-labelledby="flag-stopped-heading">
            <h3 id="flag-stopped-heading">Stopped by this flag</h3>
            {stopped.length === 0 && refusals.length === 0 ? (
              <p className="muted" data-testid="flag-stopped-empty">Nobody is waiting on this flag.</p>
            ) : (
              <>
                {stopped.length > 0 && (
                  <ul className="flag-stopped-list" data-testid="flag-stopped-crews">
                    {stopped.map((item) => (
                      <li className="flag-stopped-item" data-testid="flag-stopped-crew" key={item.id}>
                        <strong>{item.on}</strong> <span className="muted">{item.what}</span>{" "}
                        <span className="muted small">since {formatTime(item.since)}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {refusals.length > 0 && (
                  <ul className="flag-stopped-list" data-testid="flag-stopped-checks">
                    {refusals.map((check) => (
                      <li className="flag-stopped-item" data-testid="flag-stopped-check" data-kind={askerKind(check.asked_by)} key={check.id}>
                        <Badge>{askerKind(check.asked_by)}</Badge>{" "}
                        {askerKind(check.asked_by) === "robot" ? (
                          <Link to="/robot" data-testid="flag-stopped-link">{check.asked_by}</Link>
                        ) : (
                          <span>{check.asked_by}</span>
                        )}{" "}
                        <span className="muted small">
                          asked to start {check.task_id ?? check.unit ?? "a task"} at {formatTime(check.checked_at)}:{" "}
                          {check.reasons?.[0]?.text ?? check.summary}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        </section>

        <section className="flag-proposal section" aria-labelledby="proposal-heading">
          <h2 id="proposal-heading">{status === "open" ? "Proposed action" : "Action"}</h2>
          {proposals.error ? (
            <ErrorState message={proposals.error} onRetry={proposals.reload} />
          ) : proposals.loading ? (
            <Loading rows={2} />
          ) : (
            <div className="stack" data-testid="flag-proposal">
              {status === "open" && (
                <div className="flag-actions">
                  <label className="flag-rule">
                    <input
                      type="checkbox"
                      data-testid="flag-standing-rule"
                      checked={standingRule}
                      disabled={busy}
                      onChange={(event) => setStandingRule(event.target.checked)}
                    />
                    <span>Apply to similar cases</span>
                  </label>
                  <div className="row">
                    {proposal && proposal.status === "proposed" && (
                      <button
                        type="button"
                        className="button button-primary"
                        data-testid="flag-accept"
                        disabled={busy}
                        onClick={() => decide(proposal.action, proposal.id)}
                      >
                        {busy ? "Saving decision..." : actionLabel(proposal.action)}
                      </button>
                    )}
                    <button
                      type="button"
                      className="button"
                      data-testid="flag-dismiss"
                      disabled={busy}
                      onClick={() => decide("dismiss", null)}
                    >
                      Dismiss
                    </button>
                  </div>
                  {failure && (
                    <p className="flag-failure" role="alert" data-testid="flag-decision-error">
                      {failure}
                    </p>
                  )}
                </div>
              )}
              {proposal ? <ProposalBody proposal={proposal} /> : <p className="muted">No proposal for this flag yet.</p>}
            </div>
          )}
        </section>
      </div>
      {(status !== "open" || history.length > 0) && <section className="flag-audit section" aria-label="Decision record" data-testid="flag-decision-history">
        <h2>Decision record</h2>
        {decisions.error ? <ErrorState message={decisions.error} onRetry={decisions.reload} /> : decisions.loading ? <Loading rows={1} /> :
          history.length === 0 ? <p className="muted">Decision details are unavailable.</p> :
          <ul className="flag-history">{history.map((decision) => <li key={decision.id}>
            <strong>{actionLabel(decision.action)}</strong>
            <p>Decided by {decision.decided_by} <time className="num" dateTime={decision.decided_at}>{formatTime(decision.decided_at)}</time></p>
            {decision.reason && <p>{decision.reason}</p>}
            {decision.standing_rule && <p className="muted">Applies to similar cases</p>}
          </li>)}</ul>}
        <h3>Decision notices</h3>
        <p className="muted small">Messages linked to this decision record. Delivery status is shown for each message.</p>
        {record.error ? <ErrorState message={record.error} onRetry={record.reload} /> :
          outbox.error ? <ErrorState message={outbox.error} onRetry={outbox.reload} /> : outbox.loading || record.loading ? <Loading rows={1} /> :
          messages.length === 0 ? <p className="muted">No linked delivery record is available. <Link to="/crew">View crew messages</Link>.</p> :
          <ul className="flag-history" data-testid="flag-outbox">{messages.map((message) => <li key={message.id}>
            <div className="row"><strong>{message.to}</strong><span className="flag-delivery" data-status={message.status}>{humanize(message.status)}</span></div>
            <p>{message.text}</p><p className="muted small">{humanize(message.channel)} · {formatTime(message.created_at)}</p>
          </li>)}</ul>}
      </section>}
    </article>
  );
}

function DrawingChange({ diff, flag }: { diff: DrawingDiff; flag: Flag }) {
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const regions = diff.regions ?? [];
  const bounds = regions.length ? {
    left: Math.max(0, Math.min(...regions.map((region) => region.x)) - 0.12),
    top: Math.max(0, Math.min(...regions.map((region) => region.y)) - 0.12),
    right: Math.min(1, Math.max(...regions.map((region) => region.x + region.w)) + 0.12),
    bottom: Math.min(1, Math.max(...regions.map((region) => region.y + region.h)) + 0.12),
  } : null;
  const description = `Changed areas on ${diff.sheet}, revision ${diff.from_rev} compared with ${diff.to_rev}`;
  return <div className="flag-drawing">
    <figure className="flag-drawing-image">
      {unavailable ? <div className="flag-overlay-error" data-testid="flag-overlay-error">
        <ErrorState message="The drawing preview is unavailable. You can still read the sources and decide below." onRetry={() => { setSize(null); setUnavailable(false); }} />
      </div> : size && bounds ? <svg className="flag-overlay" role="img" aria-label={description} data-testid="flag-overlay"
        viewBox={`${bounds.left * size.width} ${bounds.top * size.height} ${(bounds.right - bounds.left) * size.width} ${(bounds.bottom - bounds.top) * size.height}`}>
        <image href={diff.overlay_url} width={size.width} height={size.height} onError={() => setUnavailable(true)} />
      </svg> : <img src={diff.overlay_url} alt={description} data-testid="flag-overlay"
        onError={() => setUnavailable(true)}
        onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />}
      {!unavailable && <figcaption className="flag-legend small">
        <span className="flag-legend-before">Previous: Rev {diff.from_rev}</span>
        <span className="flag-legend-after">Current: Rev {diff.to_rev}</span>
      </figcaption>}
    </figure>
    <dl className="flag-facts" data-testid="flag-drawing-facts">
      <div><dt>Drawing</dt><dd>{diff.sheet}, {diff.title}</dd></div>
      <div><dt>Current revision</dt><dd>Rev {diff.to_rev}</dd></div>
      <div><dt>Previous revision</dt><dd>Rev {diff.from_rev}</dd></div>
      <div><dt>Affected crew</dt><dd>{flag.affected?.crew || "unavailable"}</dd></div>
      <div><dt>What changed</dt><dd>{diff.summary || "unavailable"}</dd></div>
      <div><dt className="flag-link-label">Comparison</dt><dd><Link className="flag-diff-link" to={`/compare/${diff.id}`} data-testid="flag-diff-link">Open drawing comparison</Link></dd></div>
      <div><dt className="flag-link-label">Notice</dt><dd><Link className="flag-diff-link" to={`/notice/${diff.id}`} data-testid="flag-notice-link">What the crew was told</Link></dd></div>
    </dl>
  </div>;
}

function HighlightedQuote({ quote, flag, diff }: { quote: string; flag: Flag; diff?: DrawingDiff }) {
  const terms = [diff?.sheet, diff && `Rev ${diff.from_rev}`, diff && `Rev ${diff.to_rev}`, flag.affected?.unit];
  const escaped = terms.filter((term): term is string => Boolean(term)).map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp("(" + [...escaped, "\\b\\d+(?:[.,]\\d+)?\\s*(?:mm|trucks?|hours?)\\b", "\\binspection\\b", "\\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\\b"].join("|") + ")", "gi");
  return <>{quote.split(pattern).map((part, index) => index % 2 ? <mark key={index}>{part}</mark> : part)}</>;
}

function ProposalBody({ proposal }: { proposal: Proposal }) {
  const shifts = proposal.shifts ?? [];
  const summary = proposalSummary(proposal);
  const handoverMoves =
    proposal.handover_old && proposal.handover_new && proposal.handover_old !== proposal.handover_new;

  return (
    <>
      {summary && (
        <p className="flag-proposal-summary" data-testid="plan-proposal-summary">
          {summary}
        </p>
      )}
      <p>{proposal.summary}</p>
      {shifts.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Planned</th>
                <th>New</th>
              </tr>
            </thead>
            <tbody>
              {shifts.map((shift) => (
                <tr key={shift.task_id}>
                  <td>
                    <span className="stack flag-shift-task">
                      <span>{shift.name}</span>
                      <span className="muted small">{shift.crew}</span>
                    </span>
                  </td>
                  <td className="num">{formatRange(shift.old_start, shift.old_end)}</td>
                  <td className="num">{formatRange(shift.new_start, shift.new_end)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {handoverMoves && (
        <p>
          Handover moves from <strong>{formatDay(proposal.handover_old)}</strong> to{" "}
          <strong>{formatDay(proposal.handover_new)}</strong>.
        </p>
      )}
      {proposal.basis === "calculated" && <p className="muted small">Calculated from schedule dependencies</p>}
    </>
  );
}
