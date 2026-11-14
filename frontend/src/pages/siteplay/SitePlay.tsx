import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Decision, type Flag, type InboundEvent, type OutboundMessage } from "../../api/client";
import { autonomyCounts, type Counts } from "../../api/counts";
import { useQuery } from "../../api/useQuery";
import { counterLine, stepOf, waitingDecision, PLAY_MS, type Step } from "./play";
import "./siteplay.css";

type Status = "idle" | "playing" | "paused" | "waiting" | "done";

interface Props {
  /** Called after every played event, so the site model reloads its colours and open points. */
  onChanged: () => void;
}

/**
 * Play the day on the site view: the prepared events, one after another, through the same route the
 * Play next event button uses. It never decides anything: where a person has to decide, it stops and says which
 * flag, and goes on once that flag is no longer open.
 */
export function SitePlay({ onChanged }: Props) {
  const events = useQuery<InboundEvent[]>(() => api.events(), []);
  const outbox = useQuery<OutboundMessage[]>(() => api.outbox(), []);
  const decisions = useQuery<Decision[]>(() => api.decisions(), []);
  const flags = useQuery<Flag[]>(() => api.flags(), []);
  const [status, setStatus] = useState<Status>("idle");
  const [step, setStep] = useState<Step | null>(null);
  const [played, setPlayed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const busy = useRef(false);
  const decided = useRef<string[]>([]);

  const counts: Counts = useMemo(
    () => autonomyCounts(events.data ?? [], outbox.data ?? [], decisions.data ?? []),
    [events.data, outbox.data, decisions.data],
  );
  const waiting = useMemo(() => waitingDecision(flags.data ?? [], decided.current), [flags.data]);

  const reload = useCallback(() => {
    events.reload();
    outbox.reload();
    decisions.reload();
    flags.reload();
    onChanged();
  }, [events, outbox, decisions, flags, onChanged]);

  const clear = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const playOne = useCallback(async (): Promise<boolean> => {
    if (busy.current) return false;
    busy.current = true;
    try {
      const result = await api.demoNext();
      if (result === null) {
        setStatus("done");
        return false;
      }
      const known = (events.data ?? []).find((event) => event.id === result.event_id);
      const next = stepOf(result, known?.sender ?? "", known?.text ?? "", known?.channel ?? "replay");
      setStep(next);
      setPlayed((value) => value + 1);
      reload();
      if (next.decision) {
        setStatus("waiting");
        return false;
      }
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The prepared day could not be played.");
      setStatus("idle");
      return false;
    } finally {
      busy.current = false;
    }
  }, [events.data, reload]);

  const loop = useCallback(() => {
    clear();
    timer.current = window.setTimeout(async () => {
      const going = await playOne();
      if (going) loop();
    }, PLAY_MS);
  }, [clear, playOne]);

  const start = useCallback(async () => {
    setError(null);
    setStatus("playing");
    const first = await playOne();
    if (first) loop();
  }, [events.data, loop, playOne]);

  const pause = useCallback(() => {
    clear();
    setStatus((value) => (value === "playing" ? "paused" : value));
  }, [clear]);

  const resume = useCallback(async () => {
    if (status === "waiting") return;
    setStatus("playing");
    const going = await playOne();
    if (going) loop();
  }, [loop, playOne, status]);

  const advance = useCallback(async () => {
    clear();
    setStatus((value) => (value === "idle" ? "paused" : value));
    await playOne();
  }, [clear, playOne]);

  // The event list can be one fetch behind the walk, so the strip fills in who said what once it arrives.
  useEffect(() => {
    if (!step) return;
    const known = (events.data ?? []).find((event) => event.id === step.eventId);
    if (!known) return;
    const text = known.text || known.transcript || "";
    if (known.sender === step.sender && text === step.text && known.channel === step.channel) return;
    setStep({ ...step, sender: known.sender, text, channel: known.channel });
  }, [events.data, step]);

  // While a decision is outstanding, the flags are asked again: the decision is taken on the flag page, and the
  // walk has to notice it without a reload.
  useEffect(() => {
    if (status !== "waiting") return;
    const poll = window.setInterval(() => flags.reload(), 2000);
    return () => window.clearInterval(poll);
  }, [flags, status]);

  // A stopped walk goes on by itself once the flag a person had to decide is no longer open.
  useEffect(() => {
    if (status !== "waiting" || !step?.decision) return;
    const flag = (flags.data ?? []).find((item) => item.id === step.decision?.id);
    if (flag && flag.status === "open") return;
    if (!flag) {
      // A decision closes the flag, and the reload can be a moment behind: remember it and go on.
      decided.current = [...decided.current, step.decision.id];
      return;
    }
    decided.current = [...decided.current, step.decision.id];
    setStatus("playing");
    playOne().then((going) => {
      if (going) loop();
    });
  }, [flags.data, loop, playOne, status, step]);

  useEffect(() => clear, [clear]);

  useEffect(() => {
    if (status === "done" || status === "idle") clear();
  }, [clear, status]);

  return (
    <section className="panel siteplay" data-testid="siteplay-control" aria-labelledby="siteplay-heading">
      <div className="siteplay-head">
        <h2 id="siteplay-heading">Play the day</h2>
        <div className="siteplay-buttons">
          {status === "playing" ? (
            <button type="button" className="button" onClick={pause} data-testid="siteplay-pause">Pause</button>
          ) : (
            <button type="button" className="button button-primary" onClick={status === "paused" ? resume : start}
                    data-testid="siteplay-play" disabled={status === "waiting" || status === "done"}>
              {status === "paused" ? "Keep playing" : status === "done" ? "The day is over" : "Play the day"}
            </button>
          )}
          <button type="button" className="button" onClick={advance} data-testid="siteplay-step"
                  disabled={status === "playing" || status === "waiting"}>
            One event
          </button>
        </div>
      </div>
      <p className="siteplay-count num" data-testid="siteplay-count" data-played={played}
         data-auto={counts.auto} data-human={counts.human} data-status={status}>
        {counterLine(played, counts.auto, counts.human, waiting ? 1 : 0)}
      </p>
      {status === "waiting" && step?.decision ? (
        <p className="siteplay-waiting" data-testid="siteplay-waiting" role="status">
          Stopped for a decision: <Link to={`/flags/${encodeURIComponent(step.decision.id)}`}>{step.decision.title}</Link>.
          It goes on by itself once that flag is decided.
        </p>
      ) : null}
      {error ? <p className="siteplay-error" data-testid="siteplay-error" role="alert">{error}</p> : null}
      <ol className="siteplay-strip" data-testid="siteplay-strip" aria-live="polite" aria-label="What just happened">
        {step === null ? (
          <li className="siteplay-empty muted small">
            No event played yet. Play the day sends the prepared events one at a time; the site changes colour as
            they arrive.
          </li>
        ) : (
          <li className="siteplay-step" key={step.eventId} data-event={step.eventId}>
            <p className="siteplay-sender">
              <span className="siteplay-channel">{step.channel}</span> {step.sender || "the event"}
            </p>
            {step.text ? <p className="siteplay-text">{step.text}</p> : null}
            <p className="siteplay-did" data-testid="siteplay-did">Aurora {step.did.join(", ")}</p>
          </li>
        )}
      </ol>
    </section>
  );
}

