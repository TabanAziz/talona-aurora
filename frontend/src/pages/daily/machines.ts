import type { Flag, Machine, RecordEntry, StartCheck } from "../../api/client";
import type { DailyLine, DailySection } from "./report";

/** Kept against the shared golden fixture with the mail projection in dailyreport/machines.py. */
export function machineSection(day: string, record: RecordEntry[], checks: StartCheck[], machines: Machine[], flags: Flag[],
  timeZone = (typeof document !== "undefined" ? document.querySelector<HTMLMetaElement>('meta[name="site-timezone"]')?.content : null) || "Europe/Berlin",
): DailySection | null {
  const calendar = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
  const onDay = (value: string) => {
    const time = new Date(value);
    if (Number.isNaN(time.getTime())) return false;
    const parts = Object.fromEntries(calendar.formatToParts(time).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}` === day;
  };
  const time = (value: string) => new Date(value).toISOString().slice(11, 16) + " UTC";
  const line = (key: string, text: string, entryId: string): DailyLine => ({
    key, text, source: { label: "Record entry", href: "/#record-" + encodeURIComponent(entryId) },
  });
  const lines: DailyLine[] = [];
  for (const machine of [...machines].sort((a, b) => a.id.localeCompare(b.id))) {
    const identity = machine.id;
    const asked = checks.filter((check) => check.asked_by === identity && onDay(check.checked_at))
      .sort((a, b) => a.checked_at.localeCompare(b.checked_at) || a.id.localeCompare(b.id));
    const entries = record.filter((entry) => entry.actor === identity && onDay(entry.at) && !entry.refs?.check)
      .sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id));
    if (!asked.length && !entries.length) continue;
    const stopped = asked.filter((check) => check.allowed === "no");
    const first = record.find((entry) => entry.refs?.check && entry.refs.check === asked[0]?.id)?.id
      ?? entries[0]?.id ?? "r-check-" + asked[0].id;
    const label = `${machine.name} (${identity})${machine.simulated !== false ? " [simulated]" : ""}`;
    lines.push(line("machine-" + identity, `${label}: ${asked.length} start checks; ${stopped.length} stopped.`, first));
    for (const check of asked) {
      const blocked = [...new Set((check.reasons ?? []).filter((reason) => reason.blocking && reason.flag_id).map((reason) => reason.flag_id!))].sort();
      const outcome = { yes: "allowed", no: "stopped", unknown: "unknown" }[check.allowed];
      const suffix = blocked.length ? ` Flags: ${blocked.join(", ")}.` : " No blocking flag recorded.";
      const entryId = record.find((entry) => entry.refs?.check === check.id)?.id ?? "r-check-" + check.id;
      lines.push(line("check-" + check.id, `${identity} at ${time(check.checked_at)}: ${outcome}.` + suffix, entryId));
    }
    for (const entry of entries) {
      const refs = entry.refs ?? {};
      let text: string;
      if (entry.kind === "acknowledgement" && refs.sheet && refs.revision) {
        text = `${identity} confirmed ${refs.sheet} Rev ${refs.revision} at ${time(entry.at)}.`;
      } else {
        text = `${identity} at ${time(entry.at)}: ${entry.title}`;
        const detail = (entry.detail ?? "").trim();
        if (detail && detail !== entry.title) text += ": " + detail;
        const events = new Set(entry.source_event_ids ?? []);
        const raised = [...new Set(flags.filter((flag) => (entry.kind === "info" || entry.kind === "change")
          && (flag.evidence ?? []).some((evidence) => events.has(evidence.event_id))).map((flag) => flag.id))].sort();
        if (raised.length) text += ` Flags: ${raised.join(", ")}.`;
      }
      lines.push(line(entry.id, text, entry.id));
    }
  }
  return lines.length ? { key: "machines", title: "Machines", lines } : null;
}
