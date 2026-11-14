import type { Proposal, Task, TaskShift } from "../../api/client";

const DAY_MS = 24 * 60 * 60 * 1000;
export const WEEK_DAYS = 7;
export const WEEK_MS = WEEK_DAYS * DAY_MS;

function utcDay(ms: number): number {
  return Math.floor(ms / DAY_MS) * DAY_MS;
}

/** First day of the chart: the earliest day on which work is still ahead, so the demo morning is column one. */
export function weekStartFor(tasks: Task[]): number {
  const ahead = tasks.filter((task) => task.status !== "done").map((task) => new Date(task.start).getTime());
  const all = tasks.map((task) => new Date(task.start).getTime());
  const pool = (ahead.length > 0 ? ahead : all).filter((ms) => !Number.isNaN(ms));
  return utcDay(pool.length > 0 ? Math.min(...pool) : Date.now());
}

/** Weekdays between two moments, counting the end day and not the start day. Negative when `to` is earlier. */
function workingDaysBetween(from: number, to: number): number {
  const step = to >= from ? 1 : -1;
  let count = 0;
  for (let day = utcDay(from); day !== utcDay(to); ) {
    day += step * DAY_MS;
    const weekday = new Date(day).getUTCDay();
    if (weekday !== 0 && weekday !== 6) count += step;
  }
  return count;
}

function plural(n: number, unit: string): string {
  return `${n > 0 ? "+" : "-"}${Math.abs(n)} ${unit}${Math.abs(n) === 1 ? "" : "s"}`;
}

/** How far something moved: minutes or hours inside one day, working days across days. */
export function moveLabel(before: string, after: string): string {
  const from = new Date(before).getTime();
  const to = new Date(after).getTime();
  if (Number.isNaN(from) || Number.isNaN(to) || from === to) return "no change";
  if (utcDay(from) === utcDay(to)) {
    const minutes = Math.round((to - from) / 60000);
    if (Math.abs(minutes) < 60) return `${minutes > 0 ? "+" : "-"}${Math.abs(minutes)} min`;
    const hours = Math.round((minutes / 60) * 10) / 10;
    return `${hours > 0 ? "+" : "-"}${Math.abs(hours)} h`;
  }
  const days = workingDaysBetween(from, to);
  return days === 0 ? "no change" : plural(days, "day");
}

/** The label for a shifted task: by its start, or by its end when only the end moved. */
export function shiftLabel(shift: TaskShift): string {
  return shift.old_start !== shift.new_start
    ? moveLabel(shift.old_start, shift.new_start)
    : moveLabel(shift.old_end, shift.new_end);
}

export function openRescheduleProposals(proposals: Proposal[]): Proposal[] {
  return proposals.filter((p) => p.action === "reschedule" && (p.status ?? "proposed") === "proposed");
}

export function overlapsWeek(task: { start: string; end: string }, weekStart: number): boolean {
  return new Date(task.end).getTime() > weekStart && new Date(task.start).getTime() < weekStart + WEEK_MS;
}

const SNAP_MS = 2 * 60 * 60 * 1000;

/**
 * Where a time span sits in the week, as percentages of the track. Positions snap to two hours: the chart
 * reads in days, and a move of one hour would otherwise leave two bars a few pixels out of line. The exact
 * move is in the badge and the tooltip. Clamped so nothing leaves the track.
 */
export function barStyle(start: string, end: string, weekStart: number) {
  const snap = (ms: number) => Math.round(ms / SNAP_MS) * SNAP_MS;
  const from = Math.min(Math.max(snap(new Date(start).getTime() - weekStart), 0), WEEK_MS);
  const to = Math.min(Math.max(snap(new Date(end).getTime() - weekStart), from), WEEK_MS);
  return { marginInlineStart: `${(from / WEEK_MS) * 100}%`, width: `${((to - from) / WEEK_MS) * 100}%` };
}

export function weekDays(weekStart: number) {
  return Array.from({ length: WEEK_DAYS }, (_, i) => {
    const day = new Date(weekStart + i * DAY_MS);
    return { weekday: day.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" }), date: day.getUTCDate() };
  });
}
