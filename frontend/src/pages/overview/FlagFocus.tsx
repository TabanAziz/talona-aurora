import { Link } from "react-router-dom";
import { api, type DrawingDiff, type Evidence, type Flag } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { formatDay, formatNumber, formatTime, humanize } from "../../components/format";
import { Icon } from "./icons";
import { clock, distance, fileName, span } from "./logic";

const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T/;

/** Affected values come from the rules as plain strings; a timestamp reads as a time, not as ISO text. */
function factValue(value: string): string {
  return TIMESTAMP.test(value) ? formatTime(value) : value;
}

function Facts({ flag, diff }: { flag: Flag; diff: DrawingDiff | undefined }) {
  const rows: [string, string][] = [];
  if (diff) {
    rows.push(["Drawing", `${diff.sheet}, ${diff.title}`]);
    rows.push(["Revisions", `Rev ${diff.from_rev} to Rev ${diff.to_rev}`]);
  }
  for (const [key, value] of Object.entries(flag.affected ?? {})) {
    if (diff && (key === "sheet" || key === "revision")) continue;
    rows.push([humanize(key), factValue(value)]);
  }
  for (const [key, value] of Object.entries(flag.numbers ?? {})) rows.push([humanize(key), formatNumber(value)]);
  if (diff?.summary) rows.push(["What changed", diff.summary]);

  return (
    <dl className="facts" data-testid="overview-facts">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt className="muted small">{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
      {diff && (
        <div>
          <Link to={`/compare/${diff.id}`} data-testid="overview-diff-link">
            Open drawing comparison
          </Link>
        </div>
      )}
    </dl>
  );
}

/** The changed sheet with its regions framed. Regions are fractions of the sheet, so they overlap the image on purpose. */
function Sheet({ diff }: { diff: DrawingDiff }) {
  return (
    <figure className="focus-sheet" data-testid="overview-diff" data-ui-allow="overlap">
      <img src={diff.overlay_url} alt={`${diff.sheet} ${diff.title}, Rev ${diff.from_rev} against Rev ${diff.to_rev}`} />
      {(diff.regions ?? []).map((region, index) => (
        <span
          key={index}
          className="focus-region"
          title={region.label ?? humanize(region.kind)}
          style={{
            left: `${region.x * 100}%`,
            top: `${region.y * 100}%`,
            width: `${region.w * 100}%`,
            height: `${region.h * 100}%`,
          }}
        />
      ))}
    </figure>
  );
}

function Source({ item }: { item: Evidence }) {
  const attachment = fileName(item.attachment_url);
  return (
    <li className="source" data-testid="overview-source">
      <div className="source-head">
        <span>
          <strong>{humanize(item.channel)}</strong> <span className="muted">from {item.sender}</span>
        </span>
        <span className="num muted">{clock(item.at) ?? "unavailable"}</span>
      </div>
      <blockquote className="source-quote">{item.quote}</blockquote>
      {attachment && <span className="muted small">Attachment: {attachment}</span>}
    </li>
  );
}

export function FlagFocus({ flag, now }: { flag: Flag; now: number | null }) {
  const diffQuery = useQuery(() => api.diff(flag.diff_id ?? ""), [flag.diff_id], { skip: !flag.diff_id });
  const diff = diffQuery.data;
  const status = flag.status ?? "open";
  const wait = distance(flag.work_starts_at, now);
  const startDay = flag.work_starts_at ? formatDay(flag.work_starts_at) : null;

  return (
    <article className="panel focus" data-testid="overview-flag" aria-labelledby="focus-title">
      <div className="focus-top">
        <span className="row">
          <Badge tone={flag.severity === "high" ? "danger" : "warning"}>{humanize(flag.type)}</Badge>
          {status !== "open" && <Badge tone={status === "held" ? "warning" : "success"}>{status}</Badge>}
        </span>
        <span className="muted small">
          Flagged <span className="num">{clock(flag.raised_at) ?? "unavailable"}</span>
        </span>
      </div>

      <h2 id="focus-title" className="focus-title">
        {flag.title}
      </h2>

      {flag.work_starts_at && (
        <p className="focus-when">
          <Icon name="clock" />
          <strong>{wait !== null && wait >= 0 ? `Work starts in ${span(wait)}` : "Work has started"}</strong>
          <span className="muted">
            {startDay}, <span className="num">{clock(flag.work_starts_at)}</span>
          </span>
        </p>
      )}

      <p className="focus-summary">{flag.summary}</p>

      <details className="focus-evidence"><summary>View drawing and source evidence</summary><div className="focus-body">
        {diff && <Sheet diff={diff} />}
        <Facts flag={flag} diff={diff} />
      </div>

      {(flag.evidence ?? []).length > 0 && (
        <section className="stack" aria-labelledby="sources-heading">
          <h3 id="sources-heading">Sources</h3>
          <ul className="sources">
            {(flag.evidence ?? []).map((item) => (
              <Source key={`${item.event_id}-${item.at}`} item={item} />
            ))}
          </ul>
        </section>
      )}
      </details>

      <div className="focus-actions">
        <Link className="button button-primary" to={`/flags/${flag.id}`} data-testid="overview-open-flag">
          Review and decide
        </Link>
        <span className="muted small">Review the evidence and choose the next step.</span>
      </div>
    </article>
  );
}
