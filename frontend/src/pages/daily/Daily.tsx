import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Empty, ErrorState, Loading } from "../../components/States";
import {
  buildDaily,
  hasAnything,
  messagesRead,
  newestDay,
  shiftDay,
  sources,
  type DailySection,
} from "./report";
import "./daily.css";
import { machineSection } from "./machines";

const POLL_MS = 5000;

export function Daily() {
  const { date = "" } = useParams();
  const forced = useForcedState();
  const record = useQuery(api.record, [], { poll: POLL_MS });
  const flags = useQuery(api.flags, [], { poll: POLL_MS });
  const decisions = useQuery(api.decisions, [], { poll: POLL_MS });
  const waiting = useQuery(api.waiting, [], { poll: POLL_MS });
  const plan = useQuery(api.plan, [], { poll: POLL_MS });
  const events = useQuery(api.events, [], { poll: POLL_MS });
  const machines = useQuery(api.machines, [], { poll: POLL_MS });
  const checks = useQuery(api.checks, [], { poll: POLL_MS });
  const queries = [record, flags, decisions, waiting, plan, events, machines, checks];

  if (forced === "empty") return <Empty>Nothing happened on this day, so there is no report.</Empty>;
  const failed = queries.find((query) => query.error);
  if (failed) {
    return (
      <ErrorState
        message={failed.error ?? "Something went wrong."}
        onRetry={() => queries.forEach((query) => query.reload())}
      />
    );
  }
  if (queries.some((query) => query.data === undefined)) return <Loading rows={6} />;

  const day = date || newestDay(record.data ?? []) || "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    return <Empty>This address names no day. Open a day from the record.</Empty>;
  }
  const sections = buildDaily(
    day,
    record.data ?? [],
    flags.data ?? [],
    decisions.data ?? [],
    waiting.data ?? [],
    plan.data ?? null,
  );
  const machineActivity = machineSection(day, record.data ?? [], checks.data ?? [], machines.data ?? [], flags.data ?? []);
  if (machineActivity) sections.push(machineActivity);
  if (!hasAnything(sections)) {
    return <Empty>Nothing happened on this day, so there is no report.</Empty>;
  }
  return <DailyBody day={day} sections={sections} read={messagesRead(day, events.data ?? [])} />;
}

function DailyBody({ day, sections, read }: { day: string; sections: DailySection[]; read: number }) {
  const footnotes = sources(sections.flatMap((section) => section.lines));
  return (
    <article className="daily" data-testid="daily-view">
      <div className="daily-actions">
        <Link className="back-link" to={`/daily/${shiftDay(day, -1)}`} data-testid="daily-previous">
          Previous day
        </Link>
        <span className="num small muted">{day}</span>
        <Link className="back-link" to={`/daily/${shiftDay(day, 1)}`} data-testid="daily-next">
          Next day
        </Link>
        <button type="button" className="button" data-testid="daily-print" onClick={() => window.print()}>
          Print the report
        </button>
      </div>

      <header className="panel daily-head">
        <p className="muted small">Daily report</p>
        <h1>{day}</h1>
        <p className="muted small">
          Built from the Aurora record of this day, {read} message{read === 1 ? "" : "s"} read.
        </p>
      </header>

      {sections.map((section) => (
        <DaySection key={section.key} section={section} />
      ))}

      <footer className="daily-footnotes small muted">
        <h2>Sources</h2>
        <ol className="daily-footnote-list">
          {footnotes.map((item) => (
            <li key={item.href}>
              <a href={item.href} target="_blank" rel="noreferrer">
                {item.label}
              </a>
            </li>
          ))}
        </ol>
        <p>Generated from the Aurora record.</p>
      </footer>
    </article>
  );
}

function DaySection({ section }: { section: DailySection }) {
  return (
    <section className="panel daily-section" data-testid="daily-section" data-section={section.key}>
      <div className="panel-head">
        <h2>{section.title}</h2>
        <span className="num small muted">{section.lines.length}</span>
      </div>
      {section.lines.length === 0 ? (
        <p className="muted daily-nothing">Nothing reported.</p>
      ) : (
        <ul className="daily-lines">
          {section.lines.map((line) => (
            <li className="daily-line" data-testid="daily-line" data-warning={line.warning ? "true" : undefined} key={line.key}>
              <span className="daily-text">{line.text}</span>
              <a
                className="daily-source small"
                data-testid="daily-source"
                href={line.source.href}
                target="_blank"
                rel="noreferrer"
              >
                {line.source.label}
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
