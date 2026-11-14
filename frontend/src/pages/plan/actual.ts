import type { Flag, ResourceLine } from "../../api/client";

/** What the Actual and Difference columns show for one resource line. */
export type ActualCell =
  | { source: "reported"; kind: "count"; flagId: string; flagTitle: string; value: number; difference: number }
  | { source: "reported"; kind: "day"; flagId: string; flagTitle: string; day: string; move: string; late: boolean }
  | { source: "plan"; value: number; difference: number }
  | { source: "unavailable"; flagId: string | null; flagTitle: string | null; dismissed: boolean };

function sameMoment(a: string, b: string): boolean {
  const left = new Date(a).getTime();
  const right = new Date(b).getTime();
  return !Number.isNaN(left) && left === right;
}

function arrivalDifference(planned: string, reported: string): string {
  const hours = (new Date(reported).getTime() - new Date(planned).getTime()) / 3600000;
  if (hours === 0) return "no change";
  const amount = Math.abs(hours) < 1 ? Math.max(1, Math.round(Math.abs(hours) * 60)) : Math.abs(hours) < 24 ? Math.round(Math.abs(hours) * 10) / 10 : Math.round(Math.abs(hours) / 24 * 10) / 10;
  const unit = Math.abs(hours) < 1 ? "minute" : Math.abs(hours) < 24 ? "hour" : "calendar day";
  return `${amount} ${unit}${amount === 1 ? "" : "s"} ${hours > 0 ? "later" : "earlier"}`;
}

/** Deviation flags about this line, newest first. A flag raised against an older date of the line is not about it. */
function flagsFor(line: ResourceLine, flags: Flag[]): Flag[] {
  return flags
    .filter((flag) => flag.type === "plan_deviation" && flag.affected?.resource === line.id)
    .filter((flag) => {
      const planned = flag.affected?.planned_date;
      return !planned || sameMoment(planned, line.date);
    })
    .sort((a, b) => b.raised_at.localeCompare(a.raised_at));
}

/**
 * An unresolved deviation wins while its reported change has not entered the accepted plan. Nothing is derived
 * when the flag carries no number or day: the line stays unavailable and links to the flag.
 */
export function actualFor(line: ResourceLine, flags: Flag[]): ActualCell {
  const about = flagsFor(line, flags);
  const open = about.find((flag) => ["open", "held"].includes(flag.status ?? "open"));

  if (open) {
    if (line.kind === "equipment" || line.kind === "delivery") {
      // A reported arrival date stays separate from quantities available at the planned time.
      const day = open.affected?.actual_date;
      if (day && !Number.isNaN(new Date(day).getTime())) {
        return {
          source: "reported",
          kind: "day",
          flagId: open.id,
          flagTitle: open.title,
          day,
          move: arrivalDifference(line.date, day),
          late: new Date(day).getTime() > new Date(line.date).getTime(),
        };
      }
    }
    if (line.kind !== "equipment") {
      const value = open.numbers?.actual;
      if (typeof value === "number" && Number.isFinite(value)) {
        return { source: "reported", kind: "count", flagId: open.id, flagTitle: open.title, value, difference: value - line.planned };
      }
    }
    return { source: "unavailable", flagId: open.id, flagTitle: open.title, dismissed: false };
  }

  if (typeof line.actual === "number" && Number.isFinite(line.actual)) {
    return { source: "plan", value: line.actual, difference: line.actual - line.planned };
  }

  const dismissed = about.find((flag) => flag.status === "dismissed");
  if (dismissed) return { source: "unavailable", flagId: dismissed.id, flagTitle: dismissed.title, dismissed: true };
  return { source: "unavailable", flagId: null, flagTitle: null, dismissed: false };
}
