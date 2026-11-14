import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type Decision, type Flag, type Insights, type OutboundMessage, type Pattern, type Proposal, type RecordEntry, type StandingRule } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { formatNumber, formatTime, humanize } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import { buildAutonomy, buildSavings, exampleOf, patternsOf, rulesOf, scopeText, type Savings } from "./view";
import "./learned.css";

const POLL_MS = 5000;

export function Learned() {
  const forced = useForcedState();
  const insights = useQuery(api.insights, [], { poll: POLL_MS });
  const decisions = useQuery(api.decisions, [], { poll: POLL_MS });
  const outbox = useQuery(api.outbox, [], { poll: POLL_MS });
  const proposals = useQuery(api.proposals, [], { poll: POLL_MS });
  const flags = useQuery(api.flags, [], { poll: POLL_MS });
  const record = useQuery(api.record, [], { poll: POLL_MS });
  const queries = [insights, decisions, outbox, proposals, flags, record];

  if (forced === "empty") {
    return <Empty>Nothing has been learned yet. Decide a case with "Apply to similar cases" and it shows up here.</Empty>;
  }
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

  const summary = insights.data as Insights;
  return (
    <LearnedBody
      insights={summary}
      decisions={decisions.data ?? []}
      outbox={outbox.data ?? []}
      proposals={proposals.data ?? []}
      flags={flags.data ?? []}
      record={record.data ?? []}
    />
  );
}

interface BodyProps {
  insights: Insights;
  decisions: Decision[];
  outbox: OutboundMessage[];
  proposals: Proposal[];
  flags: Flag[];
  record: RecordEntry[];
}

function LearnedBody({ insights, decisions, outbox, proposals, flags, record }: BodyProps) {
  const autonomy = buildAutonomy(outbox, decisions, record);
  const savings = buildSavings(decisions, proposals, flags);
  const rules = rulesOf(insights.standing_rules ?? []);
  const patterns = patternsOf(insights.patterns ?? []);

  return (
    <article className="learned" data-testid="learned-view">
      <header className="panel learned-head">
        <p className="muted small">Learned</p>
        <h1>What Aurora learned on this site</h1>
        <p className="muted">
          Standing rules from your decisions, the patterns the record shows, what Aurora did on its own and what that
          saved. Nothing here is a forecast.
        </p>
        <p className="muted small">
          As of {formatTime(insights.generated_at)} UTC.
        </p>
      </header>

      <Section title="Rules from your decisions" count={rules.length} empty="No decision was marked for similar cases yet.">
        {rules.map((rule) => (
          <RuleRow key={rule.id} rule={rule} />
        ))}
      </Section>

      <Section title="What the record shows" count={patterns.length} empty="The record does not show a pattern yet.">
        {patterns.map((pattern) => (
          <PatternRow key={pattern.id} pattern={pattern} record={record} />
        ))}
      </Section>

      <section className="panel learned-panel" data-testid="learned-autonomy" aria-label="Autonomy">
        <div className="panel-head">
          <h2>On its own or by a human</h2>
          <span className="panel-aside">newest first</span>
        </div>
        <div className="learned-counts">
          <div className="learned-count">
            <span className="muted small">Actions Aurora took on its own</span>
            <span className="learned-number num">{autonomy.actions}</span>
          </div>
          <div className="learned-count">
            <span className="muted small">Decisions by a human</span>
            <span className="learned-number num">{autonomy.decisions}</span>
          </div>
        </div>
        {autonomy.lines.length === 0 ? (
          <p className="muted">Aurora has not acted on its own and nobody has decided yet.</p>
        ) : (
          <ul className="learned-list">
            {autonomy.lines.map((line) => (
              <li className="learned-row learned-row-line" key={line.key}>
                <span className="learned-time num muted small">{formatTime(line.at)}</span>
                <span className="learned-actor">
                  <Badge tone={line.who === "Aurora" ? "accent" : "neutral"}>{line.who}</Badge>
                </span>
                <span className="learned-line-text">{line.text}</span>
                <SourceLink href={line.href} label={line.link} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel learned-panel" data-testid="learned-savings" aria-label="Savings">
        <div className="panel-head">
          <h2>What the holds saved</h2>
          <span className="panel-aside">from the accepted proposals</span>
        </div>
        <SavingsBody savings={savings} />
      </section>

      <footer className="learned-foot muted small">
        Built from the Aurora record. The rate assumption is written next to the numbers, and a value the record does
        not hold is shown as unavailable.
      </footer>
    </article>
  );
}

function Section({ title, count, empty, children }: { title: string; count: number; empty: string; children: ReactNode }) {
  return (
    <section className="panel learned-panel" aria-label={title}>
      <div className="panel-head">
        <h2>{title}</h2>
        <span className="panel-aside">{count}</span>
      </div>
      {count === 0 ? <p className="muted">{empty}</p> : <ul className="learned-list">{children}</ul>}
    </section>
  );
}

function RuleRow({ rule }: { rule: StandingRule }) {
  return (
    <li className="learned-row" data-testid="learned-rule">
      <p className="learned-rule-text">{rule.text}</p>
      <p className="muted small">
        {rule.decided_by} decided on {formatTime(rule.decided_at)} UTC, applied{" "}
        {rule.applied_count === 1 ? "once" : `${rule.applied_count} times`}.
      </p>
      <p className="muted small">Covers {scopeText(rule.scope)}.</p>
    </li>
  );
}

function PatternRow({ pattern, record }: { pattern: Pattern; record: RecordEntry[] }) {
  return (
    <li className="learned-row" data-testid="learned-pattern">
      <div className="learned-row-title">
        <span>{pattern.statement}</span>
        <Badge tone="neutral">{humanize(pattern.kind)}</Badge>
      </div>
      {!pattern.statement.includes(`${pattern.count} of ${pattern.total}`) && (
        <p className="muted small num">{pattern.count} of {pattern.total}</p>
      )}
      {pattern.suggestion && <p className="muted small">{pattern.suggestion}</p>}
      <ul className="learned-examples">
        {(pattern.examples ?? []).map((entryId) => {
          const example = exampleOf(entryId, record);
          return (
            <li key={entryId} className="small">
              {example.href ? <a href={example.href}>{example.text}</a> : <span className="muted">{example.text}</span>}
            </li>
          );
        })}
      </ul>
    </li>
  );
}

function SavingsBody({ savings }: { savings: Savings }) {
  if (savings.rows.length === 0) {
    return (
      <p className="muted">
        No accepted hold carries a calculated saving yet, so there is no value to show.
      </p>
    );
  }
  return (
    <>
      <ul className="learned-list">
        {savings.rows.map((row) => (
          <li className="learned-row learned-row-line" key={row.key}>
            <span className="learned-line-text">{row.title}</span>
            <span className="learned-saving num small">
              {row.hours === null ? "rework hours unavailable" : `${formatNumber(row.hours)} rework h`}
            </span>
            <span className="learned-saving num small">
              {row.days === null ? "moved days unavailable" : `${formatNumber(row.days)} moved d`}
            </span>
            <Link className="learned-source small" to={row.href}>
              Flag and record entry
            </Link>
          </li>
        ))}
      </ul>
      <p className="learned-total">
        <span className="num">{savings.hours === null ? "unavailable" : `${formatNumber(savings.hours)} rework hours`}</span>{" "}
        avoided and{" "}
        <span className="num">{savings.days === null ? "unavailable" : `${formatNumber(savings.days)} days`}</span> of
        handover kept, over {savings.rows.length} accepted hold{savings.rows.length === 1 ? "" : "s"}.
      </p>
      <p className="muted small">
        Assumption: {savings.assumption ?? "the calculation behind these numbers is not recorded."}
      </p>
    </>
  );
}

function SourceLink({ href, label }: { href: string; label: string }) {
  if (href.startsWith("/api/")) {
    return (
      <a className="learned-source small" href={href} target="_blank" rel="noreferrer">
        {label}
      </a>
    );
  }
  return (
    <Link className="learned-source small" to={href}>
      {label}
    </Link>
  );
}
