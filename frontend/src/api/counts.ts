import { projectApiUrl } from "./workspace";
import type { Decision, InboundEvent, OutboundMessage, RecordEntry } from "./client";
import { actionLabel } from "../components/format";

export interface Counts {
  read: number;
  auto: number;
  human: number;
}

export interface AutonomyEntry {
  key: string;
  at: string;
  title: string;
  detail: string | null;
  href: string;
}

export const AUTONOMOUS_STATUSES: OutboundMessage["status"][] = ["sent", "simulated"];

/** A decision a person made. An automatic one carries the authorization it used and names Aurora. */
export function isHumanDecision(decision: Decision): boolean {
  if (decision.authorization_id) return false;
  return (decision.decided_by ?? "").trim().toLowerCase() !== "aurora";
}

function moment(value: string | null | undefined): number {
  if (!value) return Number.NaN;
  return Date.parse(value);
}

function newestFirst(a: AutonomyEntry, b: AutonomyEntry): number {
  return (b.at ?? "").localeCompare(a.at ?? "");
}

/**
 * The autonomy numbers, counted in one place for the Today page and the time lapse page.
 * `now` cuts the count at the moment a playback shows; without it every stored item counts.
 */
export function autonomyCounts(
  events: InboundEvent[],
  outbox: OutboundMessage[],
  decisions: Decision[],
  now: number = Number.POSITIVE_INFINITY,
): Counts {
  const reached = (value: string | null | undefined) => {
    const time = moment(value);
    return Number.isNaN(time) || time <= now;
  };
  return {
    read: events.filter((event) => reached(event.received_at)).length,
    auto: outbox.filter((message) => AUTONOMOUS_STATUSES.includes(message.status) && reached(message.created_at)).length,
    human: decisions.filter((decision) => isHumanDecision(decision) && reached(decision.decided_at)).length,
  };
}

/** The messages Aurora sent on its own, newest first, so a number can open what it counted. */
export function autonomousActions(outbox: OutboundMessage[], record: RecordEntry[]): AutonomyEntry[] {
  return outbox
    .filter((message) => AUTONOMOUS_STATUSES.includes(message.status))
    .map((message) => {
      const entry = record.find((row) => row.id === `r-out-${message.id}`);
      const source = entry?.source_event_ids?.[0];
      return {
        key: message.id,
        at: message.created_at,
        title: `${message.status === "simulated" ? "Simulated message to" : "Sent to"} ${message.to}`,
        detail: message.text,
        href: source ? projectApiUrl(`/api/events/${encodeURIComponent(source)}`) : projectApiUrl("/api/outbox"),
      };
    })
    .sort(newestFirst);
}

/** The decisions a human made, newest first, the other half of the autonomy line. */
export function humanDecisions(decisions: Decision[], record: RecordEntry[]): AutonomyEntry[] {
  return decisions
    .filter(isHumanDecision)
    .map((decision) => {
      const entry = record.find((row) => row.id === `r-dec-${decision.id}`);
      const source = entry?.source_event_ids?.[0];
      return {
        key: decision.id,
        at: decision.decided_at,
        title: `${decision.decided_by} decided: ${actionLabel(decision.action)}`,
        detail: decision.reason ?? null,
        href: source ? projectApiUrl(`/api/events/${encodeURIComponent(source)}`) : `/flags/${encodeURIComponent(decision.flag_id)}`,
      };
    })
    .sort(newestFirst);
}
