import type {
  DrawingDiff,
  InboundEvent,
  OutboundMessage,
  Plan,
  RecordEntry,
  Task,
  WaitingItem,
} from "../../api/client";

export type StepKind = "work" | "gap" | "revision" | "notice" | "confirmation";

export interface ReworkStep {
  key: string;
  kind: StepKind;
  at: string | null;
  title: string;
  detail: string | null;
  quote: string | null;
  channel: string | null;
  delivery: string | null;
  sourceEventId: string | null;
  warning: boolean;
}

export interface CostLine {
  id: string;
  name: string;
  hours: number | null;
  dependent: boolean;
}

export interface ReworkCase {
  id: string;
  unit: string;
  crew: string | null;
  task: Task | null;
  /** Hours between the work report and the revision, measured on receipt as the rule does. */
  hours: number | null;
  summary: string;
  steps: ReworkStep[];
  overlayUrl: string | null;
  change: string | null;
  costs: CostLine[];
  totalHours: number | null;
}

export interface CaseInput {
  diff: DrawingDiff;
  unit: string;
  record: RecordEntry[];
  outbox: OutboundMessage[];
  waiting: WaitingItem[];
  plan: Plan | null;
  events: InboundEvent[];
}

function time(value: string | null | undefined): number {
  const at = value ? new Date(value).getTime() : Number.NaN;
  return Number.isNaN(at) ? Number.POSITIVE_INFINITY : at;
}

function byTime(a: { at: string | null }, b: { at: string | null }): number {
  return time(a.at) - time(b.at);
}

/** "9 hours", "0.5 hours", "8.0 hours": the same wording the crew and superintendent messages use. */
export function hoursText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "an unknown number of hours";
  if (Number.isInteger(value)) return `${value} hours`;
  return `${(Math.round(value * 10) / 10).toFixed(1)} hours`;
}

export function gapText(hours: number | null): string {
  return hours === null ? "The time between the report and the revision is unavailable." : hoursText(hours);
}

const DAY_MS = 24 * 60 * 60 * 1000;

function utcDay(date: Date): number {
  return Math.floor(date.getTime() / DAY_MS) * DAY_MS;
}

/** Weekdays after the first day up to the last, the count the schedule uses for its rework assumption. */
function workingDays(start: Date, end: Date): number {
  let count = 0;
  for (let day = utcDay(start); day < utcDay(end); ) {
    day += DAY_MS;
    const weekday = new Date(day).getUTCDay();
    if (weekday !== 0 && weekday !== 6) count += 1;
  }
  return count;
}

/** The plan's own duration for a task, the same rule the rework notices state. */
export function plannedHours(task: Task): number | null {
  const start = new Date(task.start);
  const end = new Date(task.end);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) return null;
  if (utcDay(start) === utcDay(end)) return (end.getTime() - start.getTime()) / 3_600_000;
  const minutes =
    end.getUTCHours() * 60 + end.getUTCMinutes() - (start.getUTCHours() * 60 + start.getUTCMinutes());
  if (minutes <= 0) return null;
  return (minutes / 60) * (workingDays(start, end) + 1);
}

function quoteOf(event: InboundEvent | undefined): string | null {
  if (!event) return null;
  const text = (event.transcript || event.text || "").trim();
  return text || null;
}

/** The one case entry F102 writes: kind change, refs rework, diff and unit. The title is display text. */
function findCase(record: RecordEntry[], diffId: string, unit: string): RecordEntry | undefined {
  return record.find(
    (entry) =>
      entry.kind === "change" &&
      Boolean(entry.refs?.rework) &&
      entry.refs?.diff === diffId &&
      entry.refs?.unit === unit,
  );
}

export function buildCase(input: CaseInput): ReworkCase | null {
  const { diff, unit, record, outbox, waiting, plan, events } = input;
  const entry = findCase(record, diff.id, unit);
  if (!entry) return null;

  const caseId = entry.refs?.rework as string;
  const eventById = new Map(events.map((event) => [event.id, event]));
  const [workId, revisionId] = entry.source_event_ids ?? [];
  const work = eventById.get(workId ?? "");
  const revision = eventById.get(revisionId ?? "") ?? eventById.get(entry.source_event_ids?.[1] ?? "");
  const task = (plan?.tasks ?? []).find((item) => item.id === entry.refs?.task) ?? null;
  const dependents = task
    ? (plan?.tasks ?? []).filter((item) => (item.depends_on ?? []).includes(task.id))
    : [];

  const hours =
    work && revision
      ? (new Date(revision.received_at).getTime() - new Date(work.received_at).getTime()) / 3_600_000
      : null;

  const noticeEntries = outbox.filter((message) => message.id.startsWith(`o-rework-${caseId}-`));
  const crewNotice = noticeEntries.find((message) => message.id.endsWith("-crew"));
  const crew = (entry.refs?.crew as string | undefined) ?? crewNotice?.to ?? null;

  const steps: ReworkStep[] = [];
  if (work) {
    steps.push({
      key: "work",
      kind: "work",
      at: work.received_at,
      title: "Work reported",
      detail: `${work.sender}${work.channel ? ` on ${work.channel}` : ""}`,
      quote: quoteOf(work),
      channel: work.channel ?? null,
      delivery: null,
      sourceEventId: work.id,
      warning: true,
    });
  }
  steps.push({
    key: "gap",
    kind: "gap",
    at: null,
    title: gapText(hours),
    detail: "between the work report and the revision",
    quote: null,
    channel: null,
    delivery: null,
    sourceEventId: null,
    warning: hours !== null && hours < 0,
  });
  if (revision) {
    steps.push({
      key: "revision",
      kind: "revision",
      at: revision.received_at,
      title: `${diff.sheet} Rev ${diff.from_rev} to Rev ${diff.to_rev} issued`,
      detail: `${revision.sender}${revision.channel ? ` on ${revision.channel}` : ""}`,
      quote: quoteOf(revision),
      channel: revision.channel ?? null,
      delivery: null,
      sourceEventId: revision.id,
      warning: false,
    });
  }

  const notices: ReworkStep[] = noticeEntries.map((message) => {
    const notice = record.find((item) => item.refs?.message === message.id);
    return {
      key: `m-${message.id}`,
      kind: "notice",
      at: message.created_at,
      title: `Notice to ${message.to}`,
      detail: message.text,
      quote: null,
      channel: message.channel,
      delivery: message.status ?? "queued",
      sourceEventId: notice?.source_event_ids?.[0] ?? revision?.id ?? null,
      warning: message.status === "failed",
    };
  });

  const confirmations: ReworkStep[] = [];
  const decision = waiting.find((item) => item.id === `w-rework-${caseId}`);
  if (decision) {
    confirmations.push({
      key: `w-${decision.id}`,
      kind: "confirmation",
      at: decision.since,
      title: "Waiting for the superintendent to decide the rework",
      detail: decision.what,
      quote: null,
      channel: null,
      delivery: null,
      sourceEventId: decision.source_event_ids?.[1] ?? decision.source_event_ids?.[0] ?? null,
      warning: true,
    });
  }
  for (const ack of record.filter(
    (item) =>
      item.kind === "acknowledgement" &&
      item.refs?.sheet === diff.sheet &&
      item.refs?.revision === diff.to_rev &&
      (crew === null || (item.refs?.crew ?? "").toLowerCase() === crew.toLowerCase()),
  )) {
    const ackEvent = eventById.get(ack.source_event_ids?.[0] ?? "");
    confirmations.push({
      key: `a-${ack.id}`,
      kind: "confirmation",
      at: ack.at,
      title: "Confirmed",
      detail: ack.title,
      quote: quoteOf(ackEvent),
      channel: ackEvent?.channel ?? null,
      delivery: null,
      sourceEventId: ack.source_event_ids?.[0] ?? null,
      warning: false,
    });
  }

  steps.push(...notices.sort(byTime), ...confirmations.sort(byTime));

  const costs: CostLine[] = [
    ...(task ? [{ id: task.id, name: task.name, hours: plannedHours(task), dependent: false }] : []),
    ...dependents.map((item) => ({ id: item.id, name: item.name, hours: plannedHours(item), dependent: true })),
  ];
  const known = costs.map((line) => line.hours).filter((value): value is number => value !== null);
  const totalHours =
    costs.length > 0 && known.length === costs.length ? known.reduce((sum, value) => sum + value, 0) : null;

  return {
    id: caseId,
    unit,
    crew,
    task,
    hours,
    summary: summaryText(unit, crew, diff, hours),
    steps,
    overlayUrl: diff.overlay_url ?? null,
    change: diff.summary ?? null,
    costs,
    totalHours,
  };
}

/** One plain sentence a contractor can put in a change order: what was built before what arrived. */
export function summaryText(unit: string, crew: string | null, diff: DrawingDiff, hours: number | null): string {
  const who = crew ? ` by ${crew}` : "";
  const where = `in ${unit}`;
  const arrival = `${diff.sheet} Rev ${diff.to_rev}`;
  if (hours === null) {
    return `Work ${where} was reported before ${arrival} was issued, so the built work may not match the current drawing.`;
  }
  return `Work ${where}${who} was reported ${gapText(hours)} before ${arrival} was issued, so the built work may not match the current drawing.`;
}
