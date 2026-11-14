import type { RecordEntry } from "../../api/client";

const PATHS = {
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  check: "M5 12.5l4.5 4.5L19 7.5",
  flag: "M6 21V4 M6 4h11l-2 4 2 4H6",
  chat: "M4 5h16v11H9l-5 4z",
  change: "M6 3h8l4 4v14H6z M14 3v4h4 M9 12h6 M9 16h6",
  notice: "M6 17v-6a6 6 0 0 1 12 0v6l2 2H4z M10 21h4",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 11v6 M12 7.5v.5",
  decision: "M4 4h16v16H4z M8 12.5l3 3 5-6",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

export const KIND_ICON: Record<RecordEntry["kind"], IconName> = {
  change: "change",
  decision: "decision",
  notice: "notice",
  acknowledgement: "check",
  flag: "flag",
  answer: "chat",
  info: "info",
};

export const KIND_LABEL: Record<RecordEntry["kind"], string> = {
  change: "Change",
  decision: "Decision",
  notice: "Notice",
  acknowledgement: "Confirmed",
  flag: "Flag",
  answer: "Answer",
  info: "Info",
};
