import type { Answer, InboundEvent, OutboundMessage, RecordEntry } from "../../api/client";
import { Link } from "react-router-dom";
import { Badge, type Tone } from "../../components/Badge";
import { formatTime, UNAVAILABLE } from "../../components/format";
import { channelName, dayLabel, initials, isVoiceNote, type ChatItem } from "./threads";

const STATUS: Record<OutboundMessage["status"], { label: string; tone: Tone; hint: string }> = {
  sent: { label: "Sent", tone: "success", hint: "Sent through the connected channel" },
  simulated: { label: "Simulated", tone: "neutral", hint: "Simulated delivery, not sent through a live channel" },
  queued: { label: "Waiting to send", tone: "warning", hint: "Queued for the connected channel" },
  failed: { label: "Not delivered", tone: "danger", hint: "The channel refused this message" },
};

/** Times inside a chat are clock times in UTC, like the rest of the app. */
function clock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return UNAVAILABLE;
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

const AUDIO_SUFFIXES = [".mp3", ".ogg", ".m4a", ".wav"];

/** A spoken briefing arrives with an audio media URL; a drawing detail arrives with an image. */
function isAudio(url: string): boolean {
  const path = url.split("?", 1)[0].toLowerCase();
  return AUDIO_SUFFIXES.some((suffix) => path.endsWith(suffix));
}

function Media({ url, to }: { url: string; to: string }) {
  if (isAudio(url)) {
    return (
      <audio
        className="crew-audio"
        controls
        preload="none"
        src={url}
        data-testid="crew-briefing-audio"
        aria-label={`Spoken briefing for ${to}`}
      />
    );
  }
  return <img className="crew-media" src={url} alt={`Drawing detail sent to ${to}`} />;
}

function Time({ at }: { at: string }) {
  return (
    <time className="crew-time" dateTime={at} title={formatTime(at)}>
      {clock(at)}
    </time>
  );
}

function VoiceNote({ event }: { event: InboundEvent }) {
  const audio = (event.attachments ?? []).find((attachment) => attachment.kind === "audio" && attachment.url);
  return (
    <div className="crew-voice">
      {audio?.url ? (
        <audio className="crew-audio" controls preload="none" src={audio.url} aria-label={`Voice note from ${event.sender}`} />
      ) : (
        <span className="crew-voice-label">
          <span>Voice note · Audio unavailable</span>
        </span>
      )}
      <p className="crew-transcript">
        <span className="crew-label">Transcript</span>
        {event.transcript ? <span>{event.transcript}</span> : <span className="muted">{UNAVAILABLE}</span>}
      </p>
    </div>
  );
}

function Incoming({ event }: { event: InboundEvent }) {
  const voice = isVoiceNote(event);
  return (
    <div className="crew-row crew-row-in">
      <span className="crew-avatar crew-avatar-person" aria-hidden="true">
        {initials(event.sender)}
      </span>
      <div className="crew-entry">
        <p className="crew-sender">
          <strong>{event.sender}</strong>
          {event.sender_role && <span className="muted">{event.sender_role}</span>}
          <span className="crew-channel">{channelName(event.channel)}{voice ? " · Voice note" : ""}</span>
        </p>
        <div className="crew-bubble" data-testid="crew-message">
          {event.subject && <strong>{event.subject}</strong>}
          {voice && <VoiceNote event={event} />}
          {event.text && (!voice || event.text !== event.transcript) && <p>{event.text}</p>}
          {(event.attachments ?? []).filter((attachment) => attachment.kind !== "audio").map((attachment, index) => <div key={`${attachment.name}-${index}`}>
            {attachment.kind === "image" && attachment.url && <img className="crew-media" src={attachment.url} alt={attachment.name} loading="lazy" />}
            {attachment.url ? <a href={attachment.url} target="_blank" rel="noreferrer">{attachment.name}</a> : <span className="muted">{attachment.name} · File unavailable</span>}
          </div>)}
          <span className="crew-foot">
            <Time at={event.sent_at} />
          </span>
        </div>
      </div>
    </div>
  );
}

function Quote({ event }: { event: InboundEvent }) {
  const what = isVoiceNote(event) ? "Voice note" : event.text;
  return (
    <blockquote className="crew-quote">
      <Link to={`/crew?event=${encodeURIComponent(event.id)}#crew-event-${encodeURIComponent(event.id)}`}>Reply to {event.sender}</Link>
      <span className="muted">{what || UNAVAILABLE}</span>
    </blockquote>
  );
}

function Sources({ answer }: { answer: Answer }) {
  const sources = answer.sources ?? [];
  if (sources.length === 0) return null;
  return (
    <details className="crew-source-details">
      <summary>Sources ({sources.length})</summary>
      <ul className="crew-sources" aria-label="Sources of this answer">
      {sources.map((source) => (
        <li key={`${source.event_id}-${source.quote}`}>
          <Link className="crew-label" to={`/crew?event=${encodeURIComponent(source.event_id)}#crew-event-${encodeURIComponent(source.event_id)}`}>View source message</Link>
          <span>
            {source.sender}, <span className="crew-mono">{formatTime(source.at)}</span>: "{source.quote}"
          </span>
        </li>
      ))}
      </ul>
    </details>
  );
}

function Outgoing({ message, replyTo, answer }: { message: OutboundMessage; replyTo?: InboundEvent; answer?: Answer }) {
  const status = STATUS[message.status ?? "queued"];
  const buttons = message.buttons ?? [];
  return (
    <div className="crew-row crew-row-out">
      <span className="crew-avatar crew-avatar-aurora" aria-hidden="true">
        A
      </span>
      <div className="crew-entry crew-entry-wide">
        <p className="crew-sender">
          <strong>Aurora</strong>
          <span className="crew-tag">{answer ? "Answer" : buttons.includes("Confirm") ? "Confirmation requested" : "Assistant"}</span>
          <span className="crew-channel">{channelName(message.channel)}</span>
        </p>
        <div className="crew-bubble" data-testid="crew-message">
          {message.media_url && <Media url={message.media_url} to={message.to} />}
          <div className="crew-content">
            {replyTo && <Quote event={replyTo} />}
            <p>{answer ? answer.text : message.text}</p>
            {answer && <Sources answer={answer} />}
            {message.reason && <details className="crew-message-reason"><summary>Why Aurora sent this</summary><p className="muted small">{message.reason}</p></details>}
            <span className="crew-foot">
              <span className="muted small">To {message.to}</span>
              <span title={status.hint}>
                <Badge tone={status.tone}>{status.label}</Badge>
              </span>
              <Time at={message.created_at} />
            </span>
            {buttons.length > 0 && (
              <span className="crew-buttons" aria-label="Reply buttons the crew sees">
                {buttons.map((label, index) => (
                  <span className={index === 0 ? "crew-button crew-button-primary" : "crew-button"} key={label}>
                    {label}
                  </span>
                ))}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function RecordedResult({ entry, standalone = false }: { entry: RecordEntry; standalone?: boolean }) {
  const refs = entry.refs ?? {};
  const diff = refs.diff || refs.diff_id;
  const flag = refs.flag || refs.flag_id;
  const proposal = refs.proposal || refs.proposal_id;
  return <div className="crew-result" data-testid="crew-recorded-result">
    <div className="crew-result-meta"><span className="crew-label">{entry.kind === "acknowledgement" ? "Confirmation recorded" : entry.kind === "decision" ? "Decision recorded" : "Recorded result"}</span><Time at={entry.at} /></div>
    <strong>{entry.title}</strong>
    {standalone && entry.detail && <p>{entry.detail}</p>}
    <div className="crew-result-links">
      {diff && <Link to={`/compare/${encodeURIComponent(diff)}`}>Open drawing change ↗</Link>}
      {refs.sheet && refs.revision && <Link to={`/drawings?sheet=${encodeURIComponent(refs.sheet)}&revision=${encodeURIComponent(refs.revision)}`}>View {refs.sheet} Rev {refs.revision} ↗</Link>}
      {proposal && <Link to={`/plan?proposal=${encodeURIComponent(proposal)}#proposal-${encodeURIComponent(proposal)}`}>View schedule proposal ↗</Link>}
      {refs.task && !proposal && <Link to={`/plan?task=${encodeURIComponent(refs.task)}`}>View schedule task ↗</Link>}
      {flag && <Link to={`/flags/${encodeURIComponent(flag)}`}>{entry.kind === "decision" || refs.decision ? "View decision & issue" : "Review issue"} ↗</Link>}
      <Link to={`/#record-${encodeURIComponent(entry.id)}`}>View project record ↗</Link>
    </div>
  </div>;
}

function Action({ entry }: { entry: RecordEntry }) {
  return <div className="crew-row crew-row-action"><span className="crew-avatar crew-avatar-group" aria-hidden="true">{initials(entry.actor || "Project record")}</span><div className="crew-entry crew-entry-wide"><p className="crew-sender"><strong>{entry.actor || "Project record"}</strong><span className="crew-channel">Project record</span></p><RecordedResult entry={entry} standalone /></div></div>;
}

export function Message({ item, showDay }: { item: ChatItem; showDay: boolean }) {
  return (
    <li className="crew-item" id={`crew-event-${item.id}`} data-at={item.at} data-kind={item.kind}>
      {showDay && <p className="crew-day" title={item.at.slice(0, 10)}>{dayLabel(item.at)}</p>}
      {item.kind === "in" ? (
        <Incoming event={item.event} />
      ) : item.kind === "out" ? (
        <Outgoing message={item.message} replyTo={item.replyTo} answer={item.answer} />
      ) : <Action entry={item.record} />}
      {item.results.length > 0 && <div className={`crew-results crew-results-${item.kind}`} aria-label="Recorded results of this message">{item.results.map(entry => <RecordedResult key={entry.id} entry={entry} />)}</div>}
      {item.flags.length > 0 && <div className={`crew-related crew-related-${item.kind}`} aria-label="Related flags">
        {item.flags.map((flag) => <span key={flag.id} className="crew-related-item">
          <Link to={`/flags/${encodeURIComponent(flag.id)}`}>{flag.title}</Link>
          {flag.diff_id && <Link to={`/compare/${encodeURIComponent(flag.diff_id)}`}>Drawing change</Link>}
          {flag.proposal_id && <Link to={`/plan?proposal=${encodeURIComponent(flag.proposal_id)}#proposal-${encodeURIComponent(flag.proposal_id)}`}>View schedule proposal ↗</Link>}
        </span>)}
      </div>}
    </li>
  );
}
