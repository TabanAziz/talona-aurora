import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Decision, type Flag, type InboundEvent, type OutboundMessage, type RecordEntry } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { formatTime } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import {
  buildTimeline,
  clockText,
  countsAt,
  dayText,
  isoAt,
  moment,
  span,
  summarySentence,
  type TimelineItem,
} from "./timeline";
import "./timelapse.css";

const DURATION_MS = 30_000;
const TICK_MS = 80;

type Channel = InboundEvent["channel"];

export function Timelapse() {
  const forced = useForcedState();
  const events = useQuery(api.events, [], { empty: [] as InboundEvent[] });
  const flags = useQuery(api.flags, [], { empty: [] as Flag[] });
  const outbox = useQuery(api.outbox, [], { empty: [] as OutboundMessage[] });
  const decisions = useQuery(api.decisions, [], { empty: [] as Decision[] });
  const record = useQuery(api.record, [], { empty: [] as RecordEntry[] });
  const queries = [events, flags, outbox, decisions, record];

  if (forced === "empty") {
    return <Empty>Nothing has been read yet. Play the demo events on Today, then come back to the time lapse.</Empty>;
  }
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

  return (
    <Playback
      events={events.data ?? []}
      flags={flags.data ?? []}
      outbox={outbox.data ?? []}
      decisions={decisions.data ?? []}
      record={record.data ?? []}
    />
  );
}

interface PlaybackProps {
  events: InboundEvent[];
  flags: Flag[];
  outbox: OutboundMessage[];
  decisions: Decision[];
  record: RecordEntry[];
}

function Playback({ events, flags, outbox, decisions, record }: PlaybackProps) {
  const [params] = useSearchParams();
  const skipAnimation = params.get("t") === "end" || prefersReducedMotion();
  const items = useMemo(() => buildTimeline(events, flags, outbox, decisions, record), [events, flags, outbox, decisions, record]);
  const { start, end } = useMemo(() => span(items), [items]);
  const [progress, setProgress] = useState(skipAnimation ? 1 : 0);
  const [playing, setPlaying] = useState(!skipAnimation);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setProgress((value) => Math.min(1, value + (TICK_MS * speed) / DURATION_MS));
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [playing, speed]);

  useEffect(() => {
    if (progress >= 1) setPlaying(false);
  }, [progress]);

  if (items.length === 0) {
    return <Empty>Nothing has been read yet. Play the demo events on Today, then come back to the time lapse.</Empty>;
  }

  const now = start + progress * (end - start);
  const counts = countsAt(events, outbox, decisions, now);
  const shown = items.filter((item) => moment(item.at) <= now).reverse();
  const ended = progress >= 1;

  return (
    <section className="timelapse" data-testid="timelapse-view">
      <header className="timelapse-head">
        <div className="timelapse-title">
          <h1>A day on site</h1>
          <p className="muted">
            Playback of the record from its first message to its last decision. It reads only, nothing here changes the record.
          </p>
        </div>
        <div className="timelapse-clock">
          <span className="timelapse-day num small muted" data-testid="timelapse-clock-day">
            {dayText(now)}
          </span>
          <span className="timelapse-time num" data-testid="timelapse-clock" data-at={isoAt(now)}>
            {clockText(now)}
          </span>
          <span className="timezone muted small">site time (UTC)</span>
        </div>
      </header>

      <div className="timelapse-controls">
        <button
          type="button"
          className="button button-primary"
          data-testid="timelapse-play"
          onClick={() => {
            if (ended) {
              setProgress(0);
              setPlaying(true);
              return;
            }
            setPlaying(!playing);
          }}
        >
          {playing ? "Pause" : ended ? "Play again" : "Play"}
        </button>
        <button
          type="button"
          className="button"
          data-testid="timelapse-restart"
          onClick={() => {
            setProgress(0);
            setPlaying(true);
          }}
        >
          Restart
        </button>
        <button
          type="button"
          className="button"
          data-testid="timelapse-speed"
          aria-pressed={speed === 2}
          onClick={() => setSpeed(speed === 1 ? 2 : 1)}
        >
          {speed === 2 ? "2x speed" : "1x speed"}
        </button>
        <div className="timelapse-track" aria-hidden="true">
          <span className="timelapse-track-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      </div>

      <div className="timelapse-counters">
        <Count label="Messages read" value={counts.read} testId="timelapse-count-read" />
        <Count
          label="Aurora acted on its own"
          value={counts.auto}
          testId="timelapse-count-auto"
          note={`Notices, reminders, escalations and answers sent without a decision, counted from the ${counts.read} messages read`}
        />
        <Count label="Superintendent decided" value={counts.human} testId="timelapse-count-human" />
      </div>

      {ended && (
        <p className="panel timelapse-summary" data-testid="timelapse-summary">
          {summarySentence(counts)}
        </p>
      )}

      <section className="panel timelapse-feed" aria-label="What happened">
        <div className="panel-head">
          <h2>What happened</h2>
          <span className="panel-aside">
            {shown.length} of {items.length}, newest first
          </span>
        </div>
        <ol className="timelapse-items">
          {shown.map((item) => (
            <Item key={item.key} item={item} />
          ))}
        </ol>
      </section>

      <footer className="timelapse-foot muted small">
        Read-only playback of the Aurora record, {formatTime(items[items.length - 1]?.at)} at the end.
      </footer>
    </section>
  );
}

function Count({ label, value, testId, note }: { label: string; value: number; testId: string; note?: string }) {
  return (
    <div className="panel timelapse-count">
      <span className="count-label muted small">{label}</span>
      <span className="count-value num" data-testid={testId}>
        {value}
      </span>
      {note && (
        <span className="count-note muted small" data-testid={`${testId}-note`}>
          {note}
        </span>
      )}
    </div>
  );
}

const KIND_LABEL: Record<TimelineItem["kind"], string> = {
  event: "Message",
  flag: "Flag",
  action: "Aurora acted",
  decision: "Decision",
};

const KIND_TONE: Record<TimelineItem["kind"], "neutral" | "accent" | "warning"> = {
  event: "neutral",
  flag: "warning",
  action: "accent",
  decision: "neutral",
};

const KIND_TEST_ID: Record<TimelineItem["kind"], string> = {
  event: "timelapse-event",
  flag: "timelapse-flag",
  action: "timelapse-action",
  decision: "timelapse-decision",
};

function Item({ item }: { item: TimelineItem }) {
  return (
    <li className={`timelapse-item timelapse-item-${item.kind}`} data-testid={KIND_TEST_ID[item.kind]}>
      <span className="item-time num muted">{clockText(moment(item.at))}</span>
      <span className="item-mark" aria-hidden="true">
        {item.channel ? <ChannelIcon channel={item.channel} /> : <span className="mark-dot" />}
      </span>
      <div className="item-body">
        <div className="item-line">
          <strong title={item.title}>{item.title}</strong>
          <Badge tone={KIND_TONE[item.kind]}>{KIND_LABEL[item.kind]}</Badge>
        </div>
        {item.detail && <p className="item-detail">{item.detail}</p>}
      </div>
      <ItemLink item={item} />
    </li>
  );
}

function ItemLink({ item }: { item: TimelineItem }) {
  if (item.href.startsWith("/api/")) {
    return (
      <a className="item-link small" href={item.href} target="_blank" rel="noreferrer" title={item.link}>
        {item.link}
      </a>
    );
  }
  return (
    <Link className="item-link small" to={item.href} title={item.link}>
      {item.link}
    </Link>
  );
}

const ICON_PATHS: Record<Channel, string> = {
  telegram: "M14 2 2 7l4 1.5L7.5 13 10 10l4 3z",
  email: "M2 4h12v8H2zM2 4l6 5 6-5",
  whatsapp: "M4 2h2l1.5 3.5L6.5 7a9 9 0 0 0 2.5 2.5l1.5-1L14 10v2a1 1 0 0 1-1 1A11 11 0 0 1 3 3a1 1 0 0 1 1-1z",
  schedule: "M2 4h12v10H2zM2 7h12M5 2v3M11 2v3",
  replay: "M3 8a5 5 0 1 0 2-4M3 2v3h3",
  machine: "M4 5h8v7H4zM6 12v2M10 12v2M8 2v3M6.5 8h0M9.5 8h0",
};

function ChannelIcon({ channel }: { channel: Channel }) {
  return (
    <svg className="channel-icon" viewBox="0 0 16 16" aria-label={channel} role="img">
      <path d={ICON_PATHS[channel]} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
