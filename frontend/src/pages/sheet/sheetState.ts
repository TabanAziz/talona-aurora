import type { DrawingDiff, Project, WaitingItem } from "../../api/client";

export type SheetStatusKind = "superseded" | "current" | "unreported" | "unknown";

export interface SheetVerdict {
  sheet: string;
  revision: string;
  kind: SheetStatusKind;
  /** The newest revision of this sheet, so a superseded revision can name what replaced it. */
  currentRev: string;
  /** The change that replaced this revision. Only a superseded revision has one. */
  diff?: DrawingDiff;
  /** The change that introduced this revision, for the link to its comparison while it is current. */
  introducedBy?: DrawingDiff;
}

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** What a printed label should say when its revision is scanned: one of the four states. */
export function verdict(project: Project, diffs: DrawingDiff[], sheet: string, revision: string): SheetVerdict {
  const wanted = { sheet: sheet.trim(), revision: revision.trim() };
  const related = diffs.filter((diff) => same(diff.sheet, wanted.sheet));
  const inProject = project.sheets.some((known) => same(known, wanted.sheet));
  const unlinked: SheetVerdict = { ...wanted, kind: "unknown", currentRev: wanted.revision };
  if (!inProject && related.length === 0) return unlinked;

  const base = { ...wanted };

  const replacing = related.find((diff) => same(diff.from_rev, wanted.revision));
  if (replacing) {
    // follow the chain, because a revision can have been replaced more than once
    let newest = replacing.to_rev;
    const seen = new Set([wanted.revision.toLowerCase()]);
    for (let step = 0; step < related.length + 1; step += 1) {
      const lower = newest.toLowerCase();
      if (seen.has(lower)) break;
      seen.add(lower);
      const next = related.find((diff) => same(diff.from_rev, newest));
      if (!next) break;
      newest = next.to_rev;
    }
    return { ...base, kind: "superseded", currentRev: newest, diff: replacing };
  }

  const introduced = related.find((diff) => same(diff.to_rev, wanted.revision));
  if (introduced) return { ...base, kind: "current", currentRev: wanted.revision, introducedBy: introduced };

  return { ...base, kind: "unreported", currentRev: wanted.revision };
}

/** Waiting items for a revision that a crew or machine has not confirmed yet. */
export function unconfirmed(waiting: WaitingItem[], sheet: string, revision: string): WaitingItem[] {
  const wantedSheet = sheet.trim().toLowerCase();
  const wantedRev = `rev ${revision.trim()}`.toLowerCase();
  return waiting.filter((item) => {
    if (item.status === "done") return false;
    const what = item.what.toLowerCase();
    return what.includes(wantedSheet) && what.includes(wantedRev);
  });
}