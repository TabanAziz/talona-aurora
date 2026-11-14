import type { Answer, Flag, InboundEvent, OutboundMessage, RecordEntry } from "../../api/client";

type ItemContext = { flags: Flag[]; results: RecordEntry[]; people: string[] };
export type ChatItem = ItemContext & (
  | { kind: "in"; id: string; at: string; event: InboundEvent }
  | { kind: "out"; id: string; at: string; message: OutboundMessage; replyTo?: InboundEvent; answer?: Answer }
  | { kind: "action"; id: string; at: string; record: RecordEntry }
);

export interface Thread {
  key: string;
  name: string;
  category: "crew" | "inbox";
  participants: string[];
  channels: InboundEvent["channel"][];
  hasOpenFlag: boolean;
  items: ChatItem[];
}

export interface ChatData {
  crews: string[];
  events: InboundEvent[];
  outbox: OutboundMessage[];
  answers: Answer[];
  flags: Flag[];
  record?: RecordEntry[];
}

export function isSetupEvent(event: InboundEvent): boolean {
  return event.sender === "Project setup" || event.id.startsWith("workspace-");
}

export const channelName = (channel: string) => ({ telegram: "Telegram", whatsapp: "WhatsApp", email: "Email", schedule: "Project record", replay: "Site replay", machine: "Machine" }[channel] ?? channel);

export function buildThreads({ crews, events, outbox, answers, flags, record = [] }: ChatData): Thread[] {
  const team: Thread = { key: "team", name: "Team & Aurora", category: "crew", participants: [], channels: [], hasOpenFlag: false, items: [] };
  const setup: Thread = { key: "setup", name: "Project setup", category: "inbox", participants: [], channels: [], hasOpenFlag: false, items: [] };
  const byEvent = new Map(events.map(event => [event.id, event]));
  const byAnswer = new Map(answers.map(answer => [answer.event_id, answer]));
  const items = new Map<string, ChatItem>();
  const eventFlags = (id: string) => flags.filter(flag => flag.evidence?.some(source => source.event_id === id));
  const people = (...names: (string | null | undefined)[]) => [...new Set(names.filter((name): name is string => !!name?.trim()))];
  const crewOf = (role: string | null | undefined) => crews.find(crew => role?.toLowerCase().startsWith(crew.toLowerCase().split(" ")[0]));
  const append = (thread: Thread, item: ChatItem, channel?: InboundEvent["channel"]) => {
    thread.items.push(item);
    items.set(item.id, item);
    for (const person of item.people) if (!thread.participants.includes(person)) thread.participants.push(person);
    if (channel && !thread.channels.includes(channel)) thread.channels.push(channel);
  };
  for (const event of events) {
    if (event.channel === "machine") continue;
    append(isSetupEvent(event) ? setup : team, {
      kind: "in", id: event.id, at: event.sent_at, event, flags: eventFlags(event.id), results: [],
      people: people(event.sender, event.sender_role, crewOf(event.sender_role)),
    }, event.channel);
  }
  for (const message of outbox) {
    if (message.channel === "machine") continue;
    const replyTo = message.in_reply_to ? byEvent.get(message.in_reply_to) : undefined;
    const recordedAnswer = message.in_reply_to ? byAnswer.get(message.in_reply_to) : undefined;
    const answer = recordedAnswer && message.text.startsWith(recordedAnswer.text) ? recordedAnswer : undefined;
    append(replyTo && isSetupEvent(replyTo) ? setup : team, {
      kind: "out", id: message.id, at: message.created_at, message, replyTo, answer, results: [],
      flags: message.in_reply_to ? eventFlags(message.in_reply_to) : [],
      people: people(message.to, replyTo?.sender, replyTo?.sender_role, crewOf(replyTo?.sender_role)),
    }, message.channel);
  }
  for (const entry of record) {
    const linked = (entry.refs?.message && items.get(entry.refs.message)) || (entry.source_event_ids ?? []).map(id => items.get(id)).find(Boolean);
    if (linked) {
      linked.results.push(entry);
      if (entry.refs?.crew && !linked.people.includes(entry.refs.crew)) linked.people.push(entry.refs.crew);
      const flag = flags.find(flag => flag.id === (entry.refs?.flag || entry.refs?.flag_id));
      if (flag && !linked.flags.some(known => known.id === flag.id)) linked.flags.push(flag);
      continue;
    }
    if (entry.actor !== "Aurora" && entry.kind !== "decision" && entry.kind !== "acknowledgement") continue;
    if (entry.actor === "Project setup" || entry.id.startsWith("r-workspace-")) continue;
    append(team, { kind: "action", id: entry.id, at: entry.at, record: entry, results: [],
      flags: flags.filter(flag => flag.id === entry.refs?.flag), people: people(entry.actor, entry.refs?.crew) });
  }
  for (const thread of [team, setup]) {
    thread.hasOpenFlag = thread.items.some(item => item.flags.some(flag => flag.status === "open"));
    thread.items.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    thread.participants.sort((a, b) => a.localeCompare(b));
    thread.channels.sort();
  }
  return [team, setup];
}

export function initials(name: string): string {
  return name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(word => word.charAt(0).toUpperCase()).join("");
}

export function isVoiceNote(event: InboundEvent): boolean {
  return !!event.transcript || (event.attachments ?? []).some(attachment => attachment.kind === "audio");
}

export function searchableText(item: ChatItem): string {
  const text = item.kind === "out" ? item.message.text : item.kind === "action" ? `${item.record.title} ${item.record.detail ?? ""}` : [item.event.text, item.event.transcript, item.event.subject].filter(Boolean).join(" ");
  return [text, ...item.people, ...item.results.map(entry => `${entry.title} ${entry.detail ?? ""}`)].join(" ");
}

export function preview(item?: ChatItem): string {
  if (!item) return "No messages yet";
  const text = item.kind === "out" ? item.answer?.text ?? item.message.text : item.kind === "action" ? item.record.title : item.event.text || item.event.transcript || (isVoiceNote(item.event) ? "Voice note" : item.event.subject || "Attachment");
  const excerpt = text.length > 160 ? `${text.slice(0, 160).trimEnd()}…` : text;
  return item.kind === "out" ? `Aurora: ${excerpt}` : item.kind === "action" ? `${item.record.actor ?? "Project record"}: ${excerpt}` : `${item.event.sender}: ${excerpt}`;
}

export function dayLabel(at: string, now = new Date()): string {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const day = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  if (day === today) return "Today";
  if (day === today - 86400000) return "Yesterday";
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}
