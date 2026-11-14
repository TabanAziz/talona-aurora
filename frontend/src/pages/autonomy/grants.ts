import type { Authorization, AutonomySuggestion } from "../../api/client";
import { formatTime } from "../../components/format";

/** The page has no user session, so a grant is asked for on behalf of the role that decides on site. */
export const GRANTED_BY = "Superintendent";
export const REVOKED_BY = "Superintendent";

export interface DecisionLink {
  decisionId: string;
  flagId: string;
  href: string | null;
}

/**
 * The three decisions a suggestion rests on, in the order the server listed them. A missing flag id is
 * shown as unlinked rather than pointing at a page that is not the flag.
 */
export function decisionLinks(suggestion: AutonomySuggestion): DecisionLink[] {
  return suggestion.evidence_decision_ids.map((decisionId, index) => {
    const flagId = suggestion.evidence_flag_ids[index] ?? "";
    return { decisionId, flagId, href: flagId ? `/flags/${encodeURIComponent(flagId)}` : null };
  });
}

export function isActive(authorization: Authorization): boolean {
  return authorization.status === "active";
}

export function endText(authorization: Authorization): string | null {
  if (authorization.status === "revoked" && authorization.revoked_at) {
    return `Revoked${authorization.revoked_by ? ` by ${authorization.revoked_by}` : ""} on ${formatTime(authorization.revoked_at)}`;
  }
  if (authorization.status === "superseded") {
    return `Superseded by decision ${authorization.superseded_by}`;
  }
  return null;
}

export function applicationsText(authorization: Authorization): string {
  const count = authorization.applications?.length ?? 0;
  if (count === 0) return "Not applied yet";
  if (count === 1) return "Applied once";
  return `Applied ${count} times`;
}
