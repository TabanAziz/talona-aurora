import type { StartCheck, WaitingItem } from "../../api/client";

export type Asker = "person" | "agent" | "robot";

/**
 * The contract carries only the asker's name. Robots say so in their name (layout-robot-1,
 * drywall-robot-1) and the readiness check asks as readiness, so the name is all the page needs.
 */
export function askerKind(askedBy: string): Asker {
  if (/robot/i.test(askedBy)) return "robot";
  if (/agent|readiness/i.test(askedBy)) return "agent";
  return "person";
}

/**
 * The open confirmations this flag holds up: the affected crew's own confirmations, and the crews
 * confirming the same sheet and revision the flag is about.
 */
export function stoppedCrews(waiting: WaitingItem[], affected: Record<string, string>): WaitingItem[] {
  const sheet = affected.sheet ?? "";
  const revision = affected.revision ?? "";
  const crew = affected.crew ?? "";
  return waiting.filter((item) => {
    if (item.status !== "open") return false;
    if (crew && item.on === crew) return true;
    return Boolean(sheet && revision) && item.what.includes(sheet) && item.what.includes(`Rev ${revision}`);
  });
}

/** The newest checks that answered no for the flag's task or its unit, newest first as the API returns them. */
export function stoppedChecks(checks: StartCheck[], affected: Record<string, string>, limit = 5): StartCheck[] {
  const task = affected.task ?? "";
  const unit = affected.unit ?? "";
  return checks
    .filter((check) => check.allowed === "no")
    .filter((check) => (task && check.task_id === task) || (unit && check.unit === unit))
    .slice(0, limit);
}
