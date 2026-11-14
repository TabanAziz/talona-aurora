import type { Flag, RecordEntry, Task, WaitingItem } from "../../api/client";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function ms(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isNaN(time) ? null : time;
}

/** Open flags first, then by when the work starts: the next thing to decide is on top. */
export function sortFlags(flags: Flag[]): Flag[] {
  const rank = (flag: Flag) => (flag.status === "open" || flag.status === undefined ? 0 : 1);
  return [...flags].sort(
    (a, b) => rank(a) - rank(b) || (a.work_starts_at ?? "").localeCompare(b.work_starts_at ?? ""),
  );
}

/**
 * The demo data has fixed timestamps, so "now" is the newest thing the system has seen: the latest
 * record entry or flag. Every relative time on the page ("in 15 h", "tomorrow") counts from it.
 */
export function referenceTime(record: RecordEntry[], flags: Flag[]): number | null {
  const times = [...record.map((entry) => ms(entry.at)), ...flags.map((flag) => ms(flag.raised_at))].filter(
    (time): time is number => time !== null,
  );
  return times.length === 0 ? null : Math.max(...times);
}

/** "20 min", "1 h 40 min", "15 h", "3 days". */
export function span(delta: number): string {
  const minutes = Math.max(0, Math.round(delta / MINUTE));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 10) return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
  if (hours < 48) return `${Math.round(minutes / 60)} h`;
  return `${Math.round(minutes / 60 / 24)} days`;
}

/** The distance from `now` to `at`, or null when either is unknown. */
export function distance(at: string | null | undefined, now: number | null): number | null {
  const time = ms(at);
  return time === null || now === null ? null : time - now;
}

export function clock(value: string | null | undefined): string | null {
  const time = ms(value);
  if (time === null) return null;
  return new Date(time).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

/** The clock time, with the day in front when it is not the reference day: "15:52" or "Nov 10 09:12". */
export function stamp(value: string | null | undefined, now: number | null): string | null {
  const time = clock(value);
  if (time === null) return null;
  if (sameDay(value ?? "", now)) return time;
  const day = new Date(Date.parse(value ?? "")).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return `${day} ${time}`;
}

function dayKey(time: number): string {
  return new Date(time).toISOString().slice(0, 10);
}

export function sameDay(value: string, now: number | null): boolean {
  const time = ms(value);
  return time !== null && now !== null && dayKey(time) === dayKey(now);
}

/** Newest first, so a long record shows what just happened at the top. */
export function newestFirst(entries: RecordEntry[]): RecordEntry[] {
  return [...entries].sort((a, b) => (ms(b.at) ?? 0) - (ms(a.at) ?? 0));
}

/** An entry belongs to the selected flag when it was written from one of the flag's source events. */
export function inFlag(entry: RecordEntry, flag: Flag | undefined): boolean {
  if (!flag) return false;
  if (entry.refs?.flag === flag.id) return true;
  const sources = new Set((flag.evidence ?? []).map((item) => item.event_id));
  return (entry.source_event_ids ?? []).some((id) => sources.has(id));
}

export function confirmedToday(record: RecordEntry[], now: number | null): RecordEntry[] {
  return newestFirst(record.filter((entry) => entry.kind === "acknowledgement" && sameDay(entry.at, now)));
}

export function openWaiting(items: WaitingItem[]): WaitingItem[] {
  return [...items]
    .filter((item) => item.status !== "done")
    .sort((a, b) => (a.due ?? "9999").localeCompare(b.due ?? "9999"));
}

export interface SiteDay {
  /** ISO timestamp of midnight UTC of that day, for formatting. */
  day: string;
  tomorrow: boolean;
  tasks: Task[];
}

/** The next day with unfinished work after `now`. It is "tomorrow" when that is the next calendar day. */
export function nextSiteDay(tasks: Task[], now: number | null): SiteDay | null {
  if (now === null) return null;
  const upcoming = tasks
    .filter((task) => task.status !== "done" && (ms(task.start) ?? -Infinity) > now)
    .sort((a, b) => a.start.localeCompare(b.start));
  if (upcoming.length === 0) return null;
  const first = dayKey(Date.parse(upcoming[0].start));
  return {
    day: `${first}T00:00:00Z`,
    tomorrow: first === dayKey(now + DAY),
    tasks: upcoming.filter((task) => dayKey(Date.parse(task.start)) === first),
  };
}

/** Task ids that an open flag points at. */
export function riskyTasks(flags: Flag[]): Set<string> {
  const ids = new Set<string>();
  for (const flag of flags) {
    const task = flag.affected?.task;
    if (task && (flag.status === "open" || flag.status === undefined)) ids.add(task);
  }
  return ids;
}

export function fileName(url: string | null | undefined): string | null {
  if (!url) return null;
  const name = url.split("/").pop();
  return name ? decodeURIComponent(name) : null;
}
