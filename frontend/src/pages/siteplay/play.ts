import type { Flag, IngestResult } from "../../api/client";

/** How long the site view waits before it plays the next prepared event during Play the day. */
export const PLAY_MS = 2600;

export interface Step {
  /** The event this step played, as the ingest answer names it. */
  eventId: string;
  sender: string;
  text: string;
  channel: string;
  /** What Aurora did with it, in the words the strip shows. */
  did: string[];
  /** The flag this step raised and a person has to decide, if any. */
  decision: { id: string; title: string } | null;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function sentence(result: IngestResult): string[] {
  const did: string[] = [];
  const facts = result.facts?.length ?? 0;
  const notices = result.outbox?.length ?? 0;
  const flags = result.flags?.length ?? 0;
  const diffs = result.diffs?.length ?? 0;
  if (facts) did.push(`read ${plural(facts, "fact", "facts")}`);
  if (flags) did.push(`raised ${plural(flags, "flag", "flags")}`);
  if (notices) did.push(`sent ${plural(notices, "message", "messages")}`);
  if (result.answer) did.push("answered a question");
  if (diffs) did.push(`drew ${plural(diffs, "change", "changes")}`);
  if (!did.length) did.push(result.duplicate ? "seen before, so it did nothing" : "no action");
  return did;
}

/** One line of the strip for the event that just arrived. */
export function stepOf(result: IngestResult, sender: string, text: string, channel: string): Step {
  const flag = (result.flags ?? []).find((item) => item.status === "open") ?? null;
  return {
    eventId: result.event_id,
    sender,
    text,
    channel,
    did: sentence(result),
    decision: flag ? { id: flag.id, title: flag.title } : null,
  };
}

/** The open flag a person still has to decide, if the walk has to stop for one. */
export function waitingDecision(flags: Flag[], decided: string[]): Flag | null {
  return flags.find((flag) => flag.status === "open" && !decided.includes(flag.id)) ?? null;
}

/** What the counters say, in one line: played, on its own, and what a person has decided so far. */
export function counterLine(played: number, auto: number, human: number, waiting: number): string {
  const own = `${plural(auto, "message", "messages")} on its own`;
  const decided = `${plural(human, "decision", "decisions")} by a person`;
  const pending = waiting ? `, ${plural(waiting, "decision", "decisions")} waiting` : "";
  return `${plural(played, "event", "events")} played, ${own}, ${decided}${pending}`;
}
