import type { DrawingDiff, InboundEvent, OutboundMessage, RecordEntry, WaitingItem } from "../../api/client";

export type StepKind =
  | "sent"
  | "reminder"
  | "second_channel"
  | "superintendent"
  | "readback"
  | "confirmed"
  | "not_confirmed";

export interface Step {
  key: string;
  kind: StepKind;
  at: string | null;
  title: string;
  detail: string | null;
  channel: string | null;
  /** "sent" or "simulated" for messages, so a printed proof never claims delivery that did not happen. */
  delivery: string | null;
  sourceEventId: string | null;
  /** Set on the last step of a crew that has not confirmed. */
  warning: boolean;
}

/** A machine has no conversation, only three moments: Aurora queued the notice, the machine fetched it, it loaded. */
export interface MachineMoments {
  sent: string | null;
  delivery: string | null;
  received: string | null;
  loaded: string | null;
}

export interface CrewProof {
  crew: string;
  confirmed: boolean;
  due: string | null;
  steps: Step[];
  /** Set when the one asked to confirm is a registered machine. */
  machine: MachineMoments | null;
}

export interface Proof {
  arrival: { at: string; actor: string | null; eventId: string | null } | null;
  crews: CrewProof[];
  /** The latest moment the record knows about: "now" of the demo, so time left is the same on every laptop. */
  asOf: string | null;
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** "A-201 Rev C", "A-201, rev. C" or "A-201 revision C" in a message or its reason. */
function mentions(text: string, sheet: string, revision: string): boolean {
  return new RegExp(`${escape(sheet)}\\W{0,3}(rev(ision)?\\.?\\s*)${escape(revision)}\\b`, "i").test(text);
}

function time(value: string | null | undefined): number {
  const ms = value ? new Date(value).getTime() : NaN;
  return Number.isNaN(ms) ? Number.POSITIVE_INFINITY : ms;
}

function classify(message: OutboundMessage, index: number, firstChannel: string): StepKind {
  const words = `${message.reason} ${message.text}`;
  if (/read.?back/i.test(words)) return "readback";
  if (/second.?channel/i.test(message.reason)) return "second_channel";
  if (/remind/i.test(words)) return "reminder";
  if (index === 0) return "sent";
  return message.channel !== firstChannel ? "second_channel" : "reminder";
}

const TITLES: Record<StepKind, string> = {
  sent: "Notice sent",
  reminder: "Reminder",
  second_channel: "Sent again on a second channel",
  superintendent: "Superintendent told",
  readback: "Read-back question",
  confirmed: "Confirmed",
  not_confirmed: "Not confirmed",
};

/** The first message is titled by what really happened to it; a proof page may not claim a delivery. */
const DELIVERY_TITLES: Record<string, string> = {
  sent: "Notice sent",
  simulated: "Notice simulated, not sent",
  queued: "Notice queued",
  failed: "Notice not delivered",
};

const DELIVERY_SUFFIXES: Record<string, string> = {
  sent: "",
  simulated: " (simulated, not sent)",
  queued: " (queued)",
  failed: " (not delivered)",
};

function messageTitle(kind: StepKind, status: string | undefined): string {
  const delivery = status ?? "queued";
  if (kind === "sent") return DELIVERY_TITLES[delivery] ?? DELIVERY_TITLES.queued;
  return TITLES[kind] + (DELIVERY_SUFFIXES[delivery] ?? DELIVERY_SUFFIXES.queued);
}

function messageStep(message: OutboundMessage, kind: StepKind): Step {
  return {
    key: `m-${message.id}`,
    kind,
    at: message.created_at,
    title: messageTitle(kind, message.status),
    detail: message.text,
    channel: message.channel,
    delivery: message.status,
    sourceEventId: message.in_reply_to ?? null,
    warning: false,
  };
}

export function buildProof(
  diff: DrawingDiff,
  outbox: OutboundMessage[],
  waiting: WaitingItem[],
  record: RecordEntry[],
  events: InboundEvent[],
): Proof {
  const sheet = diff.sheet;
  const revision = diff.to_rev;
  const eventById = new Map(events.map((event) => [event.id, event]));
  const quoteOf = (entry: RecordEntry): string | null => {
    const source = eventById.get(entry.source_event_ids?.[0] ?? "");
    return source ? source.transcript || source.text || entry.detail || null : entry.detail ?? null;
  };

  // The mock record names the diff; the real record names the sheet and revision of the fact. A rework entry
  // carries refs.diff too and is newer than the revision, so it must never be read as the arrival: the arrival
  // is the oldest change entry that is not a rework, which is the message that brought the revision.
  const changes = record.filter(
    (entry) =>
      entry.kind === "change" &&
      !entry.refs?.rework &&
      (entry.refs?.diff === diff.id || (entry.refs?.sheet === sheet && entry.refs?.revision === revision)),
  );
  const change = [...changes].sort((a, b) => time(a.at) - time(b.at))[0];
  const arrival = change
    ? { at: change.at, actor: change.actor ?? null, eventId: change.source_event_ids?.[0] ?? null }
    : null;

  const notices = outbox
    .filter((message) => mentions(`${message.text} ${message.reason}`, sheet, revision))
    .sort((a, b) => time(a.created_at) - time(b.created_at));
  const asks = waiting.filter((item) => mentions(item.what, sheet, revision));
  const acks = record.filter(
    (entry) =>
      entry.kind === "acknowledgement" && entry.refs?.sheet === sheet && entry.refs?.revision === revision,
  );

  const toCrew = notices.filter((message) => !/superintendent/i.test(message.to));
  // A crew is a crew because someone asked it to confirm, or because a notice went to it and to nobody else
  // above it. The architect who reissued the sheet gets a notice too, and is not an affected crew.
  const asked = new Set(asks.map((item) => item.on));
  // The waiting list holds only open items, so a machine that loaded the revision is found by its confirmation;
  // its loaded time is the point of its row.
  const loadedMachines = acks.map((entry) => entry.refs?.machine).filter((name): name is string => Boolean(name));
  const crewNames = [
    ...new Set([
      ...asked,
      ...loadedMachines,
      ...toCrew.map((m) => m.to).filter((to) => asked.size === 0 || asked.has(to)),
    ]),
  ];

  const asOf = Math.max(
    ...[
      ...outbox.map((m) => time(m.created_at)),
      ...record.map((r) => time(r.at)),
      ...events.map((e) => time(e.received_at)),
    ].filter(Number.isFinite),
    Number.NEGATIVE_INFINITY,
  );

  const crews: CrewProof[] = crewNames.map((crew) => {
    const own = toCrew.filter((message) => message.to === crew);
    const first = own[0]?.channel ?? "";
    const steps: Step[] = own.map((message, index) => messageStep(message, classify(message, index, first)));

    for (const message of notices.filter((m) => /superintendent/i.test(m.to))) {
      if (message.text.toLowerCase().includes(crew.toLowerCase())) steps.push(messageStep(message, "superintendent"));
    }

    const ask = asks.find((item) => item.on === crew);
    const ack = acks.find((entry) => (entry.refs?.crew ?? "").toLowerCase() === crew.toLowerCase());
    const closed = ask !== undefined && ask.status !== "open";
    steps.sort((a, b) => time(a.at) - time(b.at));

    if (ack || closed) {
      steps.push({
        key: `c-${crew}`,
        kind: "confirmed",
        at: ack?.at ?? null,
        title: TITLES.confirmed,
        detail: ack ? quoteOf(ack) : null,
        channel: null,
        delivery: null,
        sourceEventId: ack?.source_event_ids?.[0] ?? null,
        warning: false,
      });
    } else {
      const due = ask?.due ?? null;
      const started = due !== null && Number.isFinite(asOf) && time(due) <= asOf;
      steps.push({
        key: `n-${crew}`,
        kind: "not_confirmed",
        at: null,
        title: TITLES.not_confirmed,
        detail: due === null ? "The time the work starts is unavailable." : leftText(due, asOf),
        channel: null,
        delivery: null,
        sourceEventId: null,
        warning: started,
      });
    }
    const notice = own.find((message) => message.channel === "machine");
    const machine: MachineMoments | null = notice
      ? {
          sent: notice.created_at,
          delivery: notice.status ?? null,
          received:
            record.find(
              (entry) =>
                entry.kind === "notice" &&
                entry.refs?.machine === crew &&
                entry.refs?.sheet === sheet &&
                entry.refs?.revision === revision,
            )?.at ?? null,
          loaded: ack?.refs?.machine === crew ? ack.at : null,
        }
      : null;
    return { crew, confirmed: Boolean(ack) || closed, due: ask?.due ?? null, steps, machine };
  });

  return { arrival, crews, asOf: Number.isFinite(asOf) ? new Date(asOf).toISOString() : null };
}

/** Time from the record's latest moment to the start of the work, or the fact that it started. */
export function leftText(due: string, asOf: number): string {
  if (!Number.isFinite(asOf)) return "The time left is unavailable.";
  const minutes = Math.round((time(due) - asOf) / 60000);
  if (minutes <= 0) return "Work started without the confirmation.";
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  const parts = [days ? `${days} d` : "", hours ? `${hours} h` : "", rest && !days ? `${rest} min` : ""].filter(Boolean);
  return `${parts.join(" ")} left until the work starts.`;
}
