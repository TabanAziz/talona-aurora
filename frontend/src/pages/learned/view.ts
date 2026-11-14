import { projectApiUrl } from "../../api/workspace";
import type {
  Decision,
  Flag,
  OutboundMessage,
  Pattern,
  Proposal,
  RecordEntry,
  StandingRule,
} from "../../api/client";
import { actionLabel, formatTime } from "../../components/format";

const AUTONOMOUS = ["sent", "simulated"];

export interface AutonomyLine {
  key: string;
  at: string;
  who: string;
  text: string;
  href: string;
  link: string;
}

export interface Autonomy {
  actions: number;
  decisions: number;
  lines: AutonomyLine[];
}

export interface Saving {
  key: string;
  title: string;
  hours: number | null;
  days: number | null;
  href: string;
}

export interface Savings {
  rows: Saving[];
  hours: number | null;
  days: number | null;
  assumption: string | null;
}

/** What Aurora did on its own against what a human decided, from the same record. */
export function buildAutonomy(outbox: OutboundMessage[], decisions: Decision[], record: RecordEntry[]): Autonomy {
  const sourceOf = (messageId: string): string | null => {
    const entry = record.find((row) => row.id === `r-out-${messageId}`);
    return entry?.source_event_ids?.[0] ?? null;
  };
  const lines: AutonomyLine[] = [];
  for (const message of outbox) {
    if (!AUTONOMOUS.includes(message.status ?? "queued")) continue;
    const source = sourceOf(message.id);
    lines.push({
      key: `m-${message.id}`,
      at: message.created_at,
      who: "Aurora",
      text: `${message.status === "simulated" ? "Simulated message to" : "Sent to"} ${message.to}`,
      href: source ? projectApiUrl(`/api/events/${encodeURIComponent(source)}`) : projectApiUrl("/api/outbox"),
      link: source ? "Source event" : "Record entry",
    });
  }
  for (const decision of decisions) {
    lines.push({
      key: `d-${decision.id}`,
      at: decision.decided_at,
      who: decision.decided_by ?? "the superintendent",
      text: actionLabel(decision.action),
      href: `/flags/${encodeURIComponent(decision.flag_id)}`,
      link: "Flag and record entry",
    });
  }
  lines.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  return {
    actions: outbox.filter((message) => AUTONOMOUS.includes(message.status ?? "queued")).length,
    decisions: decisions.length,
    lines: lines.slice(0, 8),
  };
}

/** The avoided rework and the moved handover of the holds a human accepted, from the proposal that was accepted. */
export function buildSavings(decisions: Decision[], proposals: Proposal[], flags: Flag[]): Savings {
  const rows: Saving[] = [];
  let assumption: string | null = null;
  for (const decision of decisions) {
    if (decision.action !== "hold_work") continue;
    const proposal = proposals.find((item) => item.id === decision.proposal_id);
    const avoided = (proposal?.params ?? {})["if_not_held"] as Record<string, unknown> | undefined;
    if (!avoided || typeof avoided !== "object") continue;
    const hours = typeof avoided.rework_hours === "number" ? avoided.rework_hours : null;
    const oldAt = typeof avoided.handover_old === "string" ? Date.parse(avoided.handover_old) : Number.NaN;
    const newAt = typeof avoided.handover_new === "string" ? Date.parse(avoided.handover_new) : Number.NaN;
    const days = Number.isFinite(oldAt) && Number.isFinite(newAt)
      ? Math.round(Math.abs(newAt - oldAt) / 86_400_000)
      : null;
    if (typeof avoided.assumption === "string" && avoided.assumption.trim()) assumption = avoided.assumption;
    const flag = flags.find((item) => item.id === decision.flag_id);
    rows.push({
      key: `s-${decision.id}`,
      title: flag?.title ?? `Flag ${decision.flag_id}`,
      hours,
      days,
      href: `/flags/${encodeURIComponent(decision.flag_id)}`,
    });
  }
  const withHours = rows.filter((row) => row.hours !== null);
  const withDays = rows.filter((row) => row.days !== null);
  return {
    rows,
    hours: withHours.length ? withHours.reduce((sum, row) => sum + (row.hours ?? 0), 0) : null,
    days: withDays.length ? withDays.reduce((sum, row) => sum + (row.days ?? 0), 0) : null,
    assumption,
  };
}

export function scopeText(scope: Record<string, unknown> | undefined): string {
  if (!scope) return "unavailable";
  const parts = Object.entries(scope)
    .filter(([key, value]) => key !== "units" && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key.replace(/_/g, " ")} ${String(value)}`);
  return parts.length ? parts.join(", ") : "every case of its kind";
}

/** The record entry behind a pattern example, as a sentence with a link to the event it came from. */
export function exampleOf(entryId: string, record: RecordEntry[]): { text: string; href: string | null } {
  const entry = record.find((row) => row.id === entryId);
  if (!entry) return { text: entryId, href: null };
  const source = entry.source_event_ids?.[0];
  return { text: `${formatTime(entry.at)}: ${entry.title}`, href: source ? projectApiUrl(`/api/events/${encodeURIComponent(source)}`) : null };
}

export function patternsOf(patterns: Pattern[]): Pattern[] {
  return [...patterns].sort((a, b) => (b.count ?? 0) - (a.count ?? 0));
}

export function rulesOf(rules: StandingRule[]): StandingRule[] {
  return [...rules].sort((a, b) => Date.parse(b.decided_at) - Date.parse(a.decided_at));
}
