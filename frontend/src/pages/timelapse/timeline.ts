import { projectApiUrl } from "../../api/workspace";
import type { Decision, Flag, InboundEvent, OutboundMessage, RecordEntry } from "../../api/client";
import { actionLabel } from "../../components/format";
import { autonomyCounts, AUTONOMOUS_STATUSES, type Counts } from "../../api/counts";

export { AUTONOMOUS_STATUSES };
export type { Counts };

type Channel = InboundEvent["channel"];

export interface TimelineItem {
  key: string;
  at: string;
  kind: "event" | "flag" | "action" | "decision";
  title: string;
  detail: string | null;
  channel: Channel | null;
  href: string;
  link: string;
}



/** Every item the page plays, in time order. A step shows only what happened before its clock. */
export function buildTimeline(
  events: InboundEvent[],
  flags: Flag[],
  outbox: OutboundMessage[],
  decisions: Decision[],
  record: RecordEntry[],
): TimelineItem[] {
  const items: TimelineItem[] = [];
  for (const event of events) {
    items.push({
      key: `event-${event.id}`,
      at: event.received_at,
      kind: "event",
      title: event.sender,
      detail: event.text || event.transcript || event.subject || "A message without text.",
      channel: event.channel,
      href: projectApiUrl(`/api/events/${encodeURIComponent(event.id)}`),
      link: "Source event",
    });
  }
  for (const flag of flags) {
    items.push({
      key: `flag-${flag.id}`,
      at: flag.raised_at,
      kind: "flag",
      title: flag.title,
      detail: beforeWork(flag),
      channel: null,
      href: `/flags/${encodeURIComponent(flag.id)}`,
      link: "Flag and record entry",
    });
  }
  for (const message of outbox) {
    if (!AUTONOMOUS_STATUSES.includes(message.status)) continue;
    const entry = record.find((row) => row.id === `r-out-${message.id}`);
    const source = entry?.source_event_ids?.[0];
    items.push({
      key: `action-${message.id}`,
      at: message.created_at,
      kind: "action",
      title: `${message.status === "simulated" ? "Simulated message to" : "Sent to"} ${message.to}`,
      detail: message.text,
      channel: message.channel,
      href: source ? projectApiUrl(`/api/events/${encodeURIComponent(source)}`) : `/api/outbox`,
      link: source ? "Source event" : "Record entry",
    });
  }
  for (const decision of decisions) {
    const entry = record.find((row) => row.id === `r-dec-${decision.id}`);
    const source = entry?.source_event_ids?.[0];
    items.push({
      key: `decision-${decision.id}`,
      at: decision.decided_at,
      kind: "decision",
      title: `${decision.decided_by} decided: ${actionLabel(decision.action)}`,
      detail: decision.reason ?? null,
      channel: null,
      href: source ? projectApiUrl(`/api/events/${encodeURIComponent(source)}`) : `/flags/${encodeURIComponent(decision.flag_id)}`,
      link: source ? "Source event" : "Flag and record entry",
    });
  }
  return items.sort((a, b) => moment(a.at) - moment(b.at));
}

export function moment(value: string | null | undefined): number {
  if (!value) return Number.NaN;
  return Date.parse(value);
}

export function span(items: TimelineItem[]): { start: number; end: number } {
  const times = items.map((item) => moment(item.at)).filter((time) => !Number.isNaN(time));
  if (times.length === 0) return { start: Number.NaN, end: Number.NaN };
  const start = Math.min(...times);
  const end = Math.max(...times);
  // One item still needs a range the clock can move over.
  return { start, end: end > start ? end : start + 3_600_000 };
}

/** The three numbers of the end screen, from the one shared counting helper. */
export function countsAt(
  events: InboundEvent[],
  outbox: OutboundMessage[],
  decisions: Decision[],
  now: number,
): Counts {
  return autonomyCounts(events, outbox, decisions, now);
}

export function clockText(now: number): string {
  if (Number.isNaN(now)) return "unavailable";
  return new Date(now).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

export function dayText(now: number): string {
  if (Number.isNaN(now)) return "unavailable";
  return new Date(now).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

/** The moment the clock shows, in ISO, so its check can tell whether the shown time ever goes backwards. */
export function isoAt(now: number): string {
  return Number.isNaN(now) ? "" : new Date(now).toISOString();
}

/** "5 h before work", the figure a flag carries next to the moment it was raised. */
export function beforeWork(flag: Flag): string | null {
  const start = moment(flag.work_starts_at);
  const raised = moment(flag.raised_at);
  if (Number.isNaN(start) || Number.isNaN(raised)) return null;
  const hours = (start - raised) / 3_600_000;
  if (hours < 0) return "after work had started";
  if (hours < 1) return "under 1 h before work";
  return `${Math.round(hours)} h before work`;
}

export function summarySentence(counts: Counts): string {
  const plural = (value: number, one: string, many: string) => `${value} ${value === 1 ? one : many}`;
  return `Aurora read ${plural(counts.read, "message", "messages")}, acted on its own ${plural(counts.auto, "time", "times")}, and the superintendent decided ${plural(counts.human, "time", "times")}.`;
}
