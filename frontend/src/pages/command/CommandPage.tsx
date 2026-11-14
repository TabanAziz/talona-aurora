import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, type CommandResponse } from "../../api/client";
import { formatRange, formatTime } from "../../components/format";
import "./command.css";

export function CommandPage() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<CommandResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [applied, setApplied] = useState(false);
  const proposal = result?.proposal;

  async function interpret(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true); setError(""); setResult(null); setApplied(false);
    try { setResult(await api.command(text.trim())); }
    catch (err) { setError(err instanceof Error ? err.message : "The instruction could not be read. Try again."); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!proposal?.flag_id || busy || applied) return;
    setBusy(true); setError("");
    try {
      await api.decide({ flag_id: proposal.flag_id, proposal_id: proposal.id, action: proposal.action });
      setApplied(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The decision could not be saved. Review the issue and try again.");
    } finally { setBusy(false); }
  }

  return <section className="command-page" data-testid="command-page">
    <header><p className="command-eyebrow">Site decisions</p><h1>Give an instruction</h1>
      <p>Describe one change to current work. Review the proposal before confirming it.</p></header>
    <form className="panel command-form" onSubmit={interpret}>
      <label htmlFor="site-instruction">What needs to change?</label>
      <textarea id="site-instruction" data-testid="command-input" value={text} disabled={busy}
        placeholder="Hold the framing in 3B until the drawing revision is confirmed."
        onChange={(event) => { setText(event.target.value); setResult(null); setApplied(false); setError(""); }} />
      <div><button className={proposal && !applied ? "button" : "button button-primary"} data-testid="command-propose" disabled={busy || !text.trim()}>
        {busy && !proposal ? "Reading instruction…" : "Review proposal"}</button></div>
    </form>
    {error && <p className="command-error" role="alert" data-testid="command-error">{error}</p>}
    <div aria-live="polite">
      {result && <section className="panel command-review" data-testid="command-result">
        {proposal ? <>
          <p className="command-eyebrow">{applied ? "Decision saved" : "Awaiting your decision"}</p>
          <h2>{proposal.summary}</h2>
          <p>{applied ? "Your decision is saved in the site record." : result.message}</p>
          {!!proposal.shifts?.length && <ul className="command-shifts">{proposal.shifts.map((shift) =>
            <li key={shift.task_id}><strong>{shift.name}</strong>
              <span>Planned: {formatRange(shift.old_start, shift.old_end)}</span>
              <span>New: {formatRange(shift.new_start, shift.new_end)}</span></li>)}</ul>}
          {proposal.handover_new && <p>Handover: {formatTime(proposal.handover_old)} → {formatTime(proposal.handover_new)}</p>}
          <div className="command-actions">
            {!applied && <button className="button button-primary" type="button" data-testid="command-confirm"
              disabled={busy || !proposal.flag_id} onClick={confirm}>{busy ? "Saving decision…" : "Confirm decision"}</button>}
            {!applied && <button className="button" type="button" disabled={busy} onClick={() => setResult(null)}>Cancel</button>}
            {proposal.flag_id && <Link className="button" to={`/flags/${encodeURIComponent(proposal.flag_id)}`}>View issue and sources</Link>}
          </div>
        </> : <><h2>No change proposed</h2><p>{result.message}</p></>}
      </section>}
    </div>
  </section>;
}
