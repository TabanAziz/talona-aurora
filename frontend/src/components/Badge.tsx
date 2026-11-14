import type { ReactNode } from "react";
import type { Flag } from "../api/client";
import { humanize } from "./format";

export type Tone = "neutral" | "accent" | "warning" | "danger" | "success";

export function Badge({ tone = "neutral", children, testId }: { tone?: Tone; children: ReactNode; testId?: string }) {
  return (
    <span className={`badge badge-${tone}`} data-testid={testId}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<NonNullable<Flag["status"]>, Tone> = {
  open: "danger",
  held: "warning",
  released: "success",
  dismissed: "neutral",
  resolved: "success",
};

export function FlagTypeBadge({ type }: { type: Flag["type"] }) {
  return <Badge tone="accent">{humanize(type)}</Badge>;
}

export function FlagStatusBadge({ status, testId }: { status: Flag["status"]; testId?: string }) {
  const value = status ?? "open";
  return (
    <Badge tone={STATUS_TONE[value]} testId={testId}>
      {value}
    </Badge>
  );
}
