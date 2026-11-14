import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { Flag, RecordEntry } from "../../api/client";
import type { Query } from "../../api/useQuery";
import { formatTime } from "../../components/format";
import { Async } from "../../components/States";
import { Icon, KIND_ICON, KIND_LABEL } from "./icons";
import { inFlag, newestFirst, stamp } from "./logic";

interface Props {
  record: Query<RecordEntry[]>;
  selected: Flag | undefined;
  now: number | null;
}

export function RecordColumn({ record, selected, now }: Props) {
  const { hash } = useLocation();
  const focused = useRef<string | null>(null);
  const [open, setOpen] = useState(false);
  const [limit, setLimit] = useState(8);
  useEffect(() => {
    if (!hash.startsWith("#record-") || !record.data || focused.current === hash) return;
    if (!open || limit < record.data.length) { setOpen(true); setLimit(record.data.length); return; }
    let id: string;
    try { id = decodeURIComponent(hash.slice(1)); } catch { return; }
    const target = document.getElementById(id);
    if (target) {
      focused.current = hash;
      target.scrollIntoView({ block: "center" });
      target.focus({ preventScroll: true });
    }
  }, [hash, record.data, open, limit]);
  return (
    <section className="overview-record-section"><details className="today-record overview-history" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
      <summary><span id="record-heading">Project history</span><span className="muted">{record.data ? `${record.data.length} entries` : ""}</span></summary>
      <Async query={record} rows={3} empty="No site updates have been recorded yet.">
        {(entries) => (
          <ol className="record-list" data-testid="record-list">
            {newestFirst(entries).slice(0, limit).map((entry) => {
              const flagged = inFlag(entry, selected);
              const setup = entry.actor === "Project setup" || entry.id.startsWith("r-workspace-");
              return (
                <li key={entry.id} id={`record-${entry.id}`} tabIndex={-1} aria-label={`${entry.title}. Record entry.`}
                  className={flagged ? "record-item record-item-flag" : "record-item"} data-testid="record-item">
                  <span className="record-icon">
                    <Icon name={KIND_ICON[entry.kind]} />
                  </span>
                  <div className="record-body">
                    <div className="record-meta">
                      <span className="num muted" title={formatTime(entry.at)}>
                        {stamp(entry.at, now) ?? "unavailable"}
                      </span>
                      <span className="record-kind">{KIND_LABEL[entry.kind]}</span>
                      {flagged && <span className="tag">In this flag</span>}
                    </div>
                    <strong className="record-title">{entry.title}</strong>
                    {entry.detail && (setup ? <details className="record-import-detail"><summary>Import details</summary><p>{entry.detail}</p></details> : <span className="record-detail" title={entry.detail}>
                        {entry.detail}
                      </span>)}
                    {entry.source_event_ids?.[0] && <Link className="record-source" to={`/crew?event=${encodeURIComponent(entry.source_event_ids[0])}`}>{setup ? "View setup source" : "Open source message"} <span aria-hidden="true">↗</span></Link>}
                    <span className="muted small">{entry.actor ?? "unavailable"}</span>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Async>
      {(record.data?.length ?? 0) > limit && <button className="button" onClick={() => setLimit(limit + 20)}>Show older entries</button>}
    </details><Link className="overview-setup-link" to="/crew?conversation=setup">View project setup conversation <span aria-hidden="true">↗</span></Link></section>
  );
}
