import type { Proposal } from "../api/client";

const DAY_MS = 86_400_000;

function dayOf(value: string | null | undefined): number | null {
  if (!value) return null;
  const at = Date.parse(value);
  return Number.isFinite(at) ? Math.floor(at / DAY_MS) : null;
}

function crews(shifts: Proposal["shifts"]): string[] {
  const seen = new Set<string>();
  for (const shift of shifts ?? []) {
    const crew = (shift.crew ?? "").trim();
    if (crew) seen.add(crew);
  }
  return [...seen];
}

/** One sentence about a proposal's effect, built only from the proposal's own fields.

A value the proposal does not hold is left out, so the sentence never estimates anything. */
export function proposalSummary(proposal: Proposal): string {
  const parts: string[] = [];
  const from = dayOf(proposal.handover_old);
  const to = dayOf(proposal.handover_new);
  if (from !== null && to !== null && to !== from) {
    const days = Math.abs(to - from);
    parts.push(`Handover ${days} ${days === 1 ? "day" : "days"} ${to > from ? "later" : "earlier"}`);
  }
  const moved = new Set((proposal.shifts ?? []).map((shift) => shift.task_id)).size;
  if (moved > 0) parts.push(`${moved} ${moved === 1 ? "task moves" : "tasks move"}`);
  const affected = crews(proposal.shifts);
  if (affected.length === 1) parts.push(`${affected[0]} affected`);
  else if (affected.length > 1) {
    parts.push(`${affected.slice(0, -1).join(", ")} and ${affected[affected.length - 1]} affected`);
  }
  return parts.length ? `${parts.join(", ")}.` : "";
}
