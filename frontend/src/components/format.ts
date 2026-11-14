// Demo data has fixed timestamps, so every time is shown in UTC: the screen looks the same on any laptop.
const TIME: Intl.DateTimeFormatOptions = {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
};
const DAY: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" };

export const UNAVAILABLE = "unavailable";

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTime(value: string | null | undefined): string {
  const date = parse(value);
  return date ? date.toLocaleString("en-US", TIME) : UNAVAILABLE;
}

export function formatDay(value: string | null | undefined): string {
  const date = parse(value);
  return date ? date.toLocaleDateString("en-US", DAY) : UNAVAILABLE;
}

/** A start and end as one phrase; the day is written once when both fall on the same day. */
export function formatRange(start: string | null | undefined, end: string | null | undefined): string {
  const from = parse(start);
  const to = parse(end);
  if (!from || !to) return UNAVAILABLE;
  if (from.toISOString().slice(0, 10) !== to.toISOString().slice(0, 10)) {
    return `${formatTime(start)} to ${formatTime(end)}`;
  }
  const clock = to.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
  return `${formatTime(start)} to ${clock}`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function formatSigned(value: number): string {
  const text = formatNumber(Math.abs(value));
  if (value > 0) return `+${text}`;
  if (value < 0) return `-${text}`;
  return text;
}

/** "plan_deviation" to "Plan deviation". */
export function humanize(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const ACTION_LABELS: Record<string, string> = {
  hold_work: "Hold work",
  release_work: "Release work",
  reschedule: "Accept changed plan",
  notify_crew: "Notify crew",
  request_ack: "Ask for confirmation",
  dismiss: "Dismiss",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? humanize(action);
}
