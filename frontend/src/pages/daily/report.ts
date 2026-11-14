import { projectApiUrl } from "../../api/workspace";
import type { Decision, Flag, InboundEvent, Plan, RecordEntry, WaitingItem } from "../../api/client";
import { actionLabel, formatTime, humanize } from "../../components/format";

export interface DailySource {
  label: string;
  href: string;
}

export interface DailyLine {
  key: string;
  text: string;
  source: DailySource;
  warning?: boolean;
}

export interface DailySection {
  key: string;
  title: string;
  lines: DailyLine[];
}

const STATUS_LABEL: Record<string, string> = {
  open: "open",
  held: "held, waiting for you",
  resolved: "resolved",
  dismissed: "dismissed",
  released: "released",
};

/** The UTC day of an ISO timestamp, the day the rest of the screen shows. */
export function dayOf(value: string | null | undefined): string | null {
  if (!value || value.length < 10) return null;
  return value.slice(0, 10);
}

function onDay(day: string, value: string | null | undefined): boolean {
  return dayOf(value) === day;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function askedBy(item: WaitingItem, end: number): boolean {
  const asked = Date.parse(item.since);
  // An item with no readable ask time is still owed, so it stays rather than silently dropping out of every day.
  if (Number.isNaN(asked)) return true;
  return asked < end;
}

function source(label: string, href: string): DailySource {
  return { label, href };
}

function eventSource(eventId: string | undefined): DailySource | null {
  return eventId ? source(`Source ${eventId}`, projectApiUrl(`/api/events/${encodeURIComponent(eventId)}`)) : null;
}

function entrySource(entry: RecordEntry): DailySource {
  const events = entry.source_event_ids ?? [];
  const event = eventSource(events[0]);
  if (event) return event;
  const flag = entry.refs?.flag;
  if (flag) return source(`Flag ${flag}`, `/flags/${encodeURIComponent(flag)}`);
  return source("Plan", "/plan");
}

/** The record writes inspections and drawing changes with the same kind, so the title and the refs decide. */
function bucket(entry: RecordEntry): "work" | "changes" | "inspections" {
  if (entry.title.toLowerCase().includes("inspection")) return "inspections";
  if (entry.kind === "acknowledgement" || entry.refs?.sheet || /Rev \S+/.test(entry.title)) return "changes";
  return "work";
}

function sentence(entry: RecordEntry): string {
  const detail = (entry.detail ?? "").trim();
  if (!detail || detail === entry.title) return `${entry.title}.`;
  return `${entry.title}: ${detail}`;
}

export function buildDaily(
  day: string,
  record: RecordEntry[],
  flags: Flag[],
  decisions: Decision[],
  waiting: WaitingItem[],
  plan: Plan | null,
): DailySection[] {
  const entries = record.filter((entry) => onDay(day, entry.at));
  const decisionsByFlag = new Map(decisions.map((decision) => [decision.flag_id, decision]));
  const work: DailyLine[] = [];
  const inspections: DailyLine[] = [];
  const changes: DailyLine[] = [];
  const sent: DailyLine[] = [];

  for (const entry of entries) {
    // A start check is someone asking, not something that happened on site, and its title holds a name the caller chose.
    if (entry.refs?.check) continue;
    if (entry.kind === "notice") {
      const failed = entry.title.toLowerCase().includes("not delivered") || entry.title.toLowerCase().includes("failed");
      sent.push({ key: entry.id, text: sentence(entry), source: entrySource(entry), warning: failed });
      continue;
    }
    if (entry.kind !== "info" && entry.kind !== "change" && entry.kind !== "acknowledgement") continue;
    const line: DailyLine = { key: entry.id, text: sentence(entry), source: entrySource(entry) };
    const target = bucket(entry);
    if (target === "inspections") inspections.push(line);
    else if (target === "changes") changes.push(line);
    else work.push(line);
  }

  const resources: DailyLine[] = (plan?.resources ?? [])
    .filter((resource) => onDay(day, resource.date))
    .map((resource) => ({
      key: `resource-${resource.id}`,
      text:
        `${resource.item}: planned ${resource.planned} ${resource.unit}` +
        `, actual ${resource.actual === null || resource.actual === undefined ? "not reported" : `${resource.actual} ${resource.unit}`}.`,
      source: source("Plan", "/plan"),
    }));

  const flagLines: DailyLine[] = flags
    .filter((flag) => onDay(day, flag.raised_at))
    .map((flag) => {
      const decision = decisionsByFlag.get(flag.id);
      const taken = decision ? `${actionLabel(decision.action)} by ${decision.decided_by}.` : "No decision yet.";
      const evidence = flag.evidence?.[0]?.event_id;
      return {
        key: `flag-${flag.id}`,
        text: `${flag.title} (${STATUS_LABEL[flag.status] ?? humanize(flag.status)}). ${flag.summary} ${taken}`,
        source: eventSource(evidence) ?? source(`Flag ${flag.id}`, `/flags/${encodeURIComponent(flag.id)}`),
        warning: flag.status === "open" || flag.status === "held",
      };
    });

  const dayEnd = Date.parse(`${day}T00:00:00Z`) + DAY_MS;
  const waitingLines: DailyLine[] = waiting
    .filter((item) => item.status === "open" && askedBy(item, dayEnd))
    .map((item) => ({
      key: `waiting-${item.id}`,
      text: `${item.on}: ${item.what}.` + (item.due ? ` Due ${formatTime(item.due)} UTC.` : " No due time on record."),
      source: eventSource((item.source_event_ids ?? [])[0]) ?? source("Plan", "/plan"),
    }));

  return [
    { key: "work", title: "Work announced and started", lines: work },
    { key: "changes", title: "Drawing changes and confirmations", lines: changes },
    { key: "inspections", title: "Inspections", lines: inspections },
    { key: "resources", title: "Deliveries and equipment against the plan", lines: resources },
    { key: "flags", title: "Flags and the decision taken", lines: flagLines },
    { key: "sent", title: "What Aurora sent on its own", lines: sent },
    { key: "waiting", title: "Still waiting on whom", lines: waitingLines },
  ];
}

/** The day to open when the address names none: the day of the newest record entry. */
export function newestDay(record: RecordEntry[]): string | null {
  let newest: RecordEntry | null = null;
  for (const entry of record) {
    if (!newest || Date.parse(entry.at) > Date.parse(newest.at)) newest = entry;
  }
  return newest ? dayOf(newest.at) : null;
}

export function shiftDay(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function sources(lines: DailyLine[]): DailySource[] {
  const seen = new Map<string, DailySource>();
  for (const line of lines) {
    if (!seen.has(line.source.href)) seen.set(line.source.href, line.source);
  }
  return [...seen.values()];
}

export function messagesRead(day: string, events: InboundEvent[]): number {
  return events.filter((event) => onDay(day, event.received_at)).length;
}

export function hasAnything(sections: DailySection[]): boolean {
  return sections.some((section) => section.lines.length > 0);
}
