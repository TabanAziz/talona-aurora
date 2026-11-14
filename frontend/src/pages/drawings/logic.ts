import type { DrawingDiff, WaitingItem } from "../../api/client";
import type { DrawingSheet } from "./api";

export function revisionOf(sheet: DrawingSheet, requested: string | null) {
  return sheet.revisions.find((rev) => rev.revision === (requested ?? sheet.current_revision)) ?? sheet.revisions[sheet.revisions.length - 1] ?? null;
}
export function comparisonsOf(diffs: DrawingDiff[], sheet: string, revision: string) {
  return diffs.filter((diff) => diff.sheet === sheet && (diff.from_rev === revision || diff.to_rev === revision));
}
export function confirmationsOf(waiting: WaitingItem[], sheet: string, revision: string) {
  const escaped = revision.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const revisionPattern = new RegExp(`\\brev(?:ision)?\\s+${escaped}(?![\\w-])`, "i");
  const sheetPattern = new RegExp(`(^|[^\\w-])${sheet.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`, "i");
  return waiting.filter((item) => sheetPattern.test(item.what) && revisionPattern.test(item.what));
}
export function receivedLabel(value: string | null) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}
