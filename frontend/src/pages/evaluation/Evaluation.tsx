import { useForcedState } from "../../api/useQuery";
import { Empty } from "../../components/States";
import data from "./reports/data.json";
import "./evaluation.css";

/** The measures the pipeline run and every stress variant share (eval/pipeline and eval/stress report.json). */
interface Summary {
  cases: number;
  cases_with_problem: number;
  cases_without_problem: number;
  cases_passed: number;
  cases_with_errors: number;
  expected_flags: number;
  flags_found: number;
  missed_problems: number;
  false_alarms: number;
  no_problem_cases_with_a_flag: number;
  timing_on_expected_event: string;
  timing_not_before_information: string;
  timing_before_work_start: string;
  evidence_cites_arrived_events: string;
  final_status_as_expected?: string;
}

interface Case {
  id: string;
  note: string;
  expected: number;
  passed: boolean;
  hits?: { flag_id: string; type: string; raised_by: string }[];
  missed?: { type: string; expected_by?: string }[];
  false_alarms?: { flag_id: string; type: string }[];
  errors?: string[];
}

interface Kind {
  kind: string;
  style: string | null;
  summary: Summary;
  skipped_cases: string[];
  skipped_messages: number;
  calls: { real: number; replay: number } | number;
  failed: { case: string; note: string; result?: Case; events?: { event: string; text: string; facts?: { type: string; quote?: string }[] }[] }[];
}

interface VoiceLevel {
  added_snr_db: number;
  n: number;
  keys_retained: number;
  same_facts: number;
  valid_baselines: number;
  safe_failures: number;
  wrong_critical_facts: number;
  unrejected_failures: number;
}

interface Voice {
  meta: { when: string; model?: string; speech_model?: string };
  scope?: string;
  complete?: boolean;
  levels: VoiceLevel[];
  limitations?: string[];
}

interface RunMeta {
  when: string;
  mode: string;
  model: string;
  commit?: string;
  real_areas?: string[];
  mock_areas?: string[];
}

/** A report is only shown when the part the page reads is there; a half-written one says Not run yet. */
function completeDetection(report: Bundle["pipeline"]): boolean {
  return Boolean(report && report.meta?.when && report.summary && typeof report.summary.cases === "number" && Array.isArray(report.cases));
}

function completeStress(report: Bundle["stress"]): boolean {
  return Boolean(
    report && report.meta?.when && Array.isArray(report.kinds) &&
      report.kinds.every((kind) => typeof kind.summary?.cases === "number"),
  );
}

function completeVoice(report: Bundle["voice"]): boolean {
  return Boolean(report && report.meta?.when && Array.isArray(report.levels));
}

interface Bundle {
  pipeline: { meta: RunMeta; summary: Summary; cases: Case[]; limitations: string[] } | null;
  stress: { meta: RunMeta; limitations: string[]; kinds: Kind[] } | null;
  voice: Voice | null;
}

const bundle = data as unknown as Bundle;

export function Evaluation() {
  const forced = useForcedState();
  if (forced === "empty") return <Empty>No evaluation report is on record.</Empty>;

  return (
    <article className="evaluation" data-testid="evaluation-view">
      <header className="evaluation-head">
        <h1>Evaluation</h1>
        <p className="muted">
          What the detection proves on fixed cases, measured against expected answers kept out of the product. Every
          number below comes from a committed report.
        </p>
      </header>

      <Detection report={bundle.pipeline} />
      <Stress report={bundle.stress} />
      <Voice report={bundle.voice} />
      <Limitations bundle={bundle} />
      <Cases report={bundle.pipeline} />
    </article>
  );
}

function RunLine({ meta }: { meta: RunMeta }) {
  return (
    <p className="evaluation-run small" data-testid="evaluation-run">
      Aurora evaluation run <span className="num">{meta.when}</span>, mode {meta.mode ?? "unknown"}
      {meta.commit && (
        <>
          , measured on commit <span className="mono">{meta.commit.slice(0, 12)}</span>
        </>
      )}
    </p>
  );
}

function Areas({ meta }: { meta: RunMeta }) {
  const real = meta.real_areas ?? [];
  const mocked = meta.mock_areas ?? [];
  if (real.length === 0 && mocked.length === 0) {
    return <p className="muted small" data-testid="evaluation-areas">The report does not name its areas.</p>;
  }
  return (
    <p className="evaluation-areas small" data-testid="evaluation-areas">
      Areas with a real module: {real.join(", ") || "none"}. Areas still on their mock: {mocked.join(", ") || "none"}.
    </p>
  );
}

function Measure({ name, value, note, testId = "evaluation-measure" }: { name: string; value: string; note?: string; testId?: string }) {
  return (
    <div className="evaluation-measure" data-testid={testId} data-measure={name}>
      <span className="muted small">{name}</span>
      <span className="evaluation-value num">{value}</span>
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

function Detection({ report }: { report: Bundle["pipeline"] }) {
  if (!report || !completeDetection(report)) {
    return (
      <section className="panel evaluation-panel">
        <h2>Detection</h2>
        <p className="muted">
          Not run yet: {report ? "the committed detection report is incomplete." : "no committed detection report."}
        </p>
      </section>
    );
  }
  const s = report.summary;
  return (
    <section className="panel evaluation-panel" data-testid="evaluation-detection">
      <div className="panel-head">
        <h2>Detection on fixed cases</h2>
        <span className="panel-aside">{s.cases} cases</span>
      </div>
      <RunLine meta={report.meta} />
      <Areas meta={report.meta} />
      <div className="evaluation-grid">
        <Measure name="Cases passed" value={`${s.cases_passed} of ${s.cases}`} note={`${s.cases_with_problem} with a problem, ${s.cases_without_problem} without`} />
        <Measure name="Flags found" value={`${s.flags_found} of ${s.expected_flags}`} note="matching an expected flag" />
        <Measure name="Missed problems" value={String(s.missed_problems)} note={`of ${s.expected_flags} expected flags`} />
        <Measure name="False alarms" value={`${s.false_alarms} in ${s.no_problem_cases_with_a_flag} of ${s.cases_without_problem}`} note="cases without a problem" />
        <Measure name="Raised by the completing event" value={s.timing_on_expected_event} note="events that finished the evidence" />
        <Measure name="Not before its evidence" value={s.timing_not_before_information} note="flags that waited for their source" />
        <Measure name="Before the work starts" value={s.timing_before_work_start} note="flags that arrived in time" />
        <Measure name="Evidence cites arrived events" value={s.evidence_cites_arrived_events} note="every flag" />
      </div>
    </section>
  );
}

function Stress({ report }: { report: Bundle["stress"] }) {
  if (!report || !completeStress(report)) {
    return (
      <section className="panel evaluation-panel">
        <h2>Stress test</h2>
        <p className="muted">
          Not run yet: {report ? "the committed stress report is incomplete." : "no committed stress report."}
        </p>
      </section>
    );
  }
  return (
    <section className="panel evaluation-panel" data-testid="evaluation-stress">
      <div className="panel-head">
        <h2>Stress test on rewritten messages</h2>
        <span className="panel-aside">{report.kinds.length} variants</span>
      </div>
      <RunLine meta={report.meta} />
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Variant</th>
              <th className="num">Cases run</th>
              <th className="num">Flags found</th>
              <th className="num">Missed</th>
              <th className="num">False alarms</th>
              <th className="num">Skipped</th>
            </tr>
          </thead>
          <tbody>
            {report.kinds.map((kind) => {
              const s = kind.summary;
              const skipped = kind.skipped_cases?.length ?? 0;
              return (
                <tr key={kind.kind} data-testid="evaluation-kind" data-kind={kind.kind}>
                  <td>{kindLabel(kind.kind)}</td>
                  <td className="num">
                    {s.cases} of {s.cases + skipped}
                  </td>
                  <td className="num">
                    {s.flags_found} of {s.expected_flags}
                  </td>
                  <td className="num">{s.missed_problems}</td>
                  <td className="num">{s.false_alarms}</td>
                  <td className="num">{skipped}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        A skipped case is one whose rewrite lost a unit, sheet, revision, count or day, so it was never run with the
        clean text. It is coverage we do not claim.
      </p>
      <StressFailures kinds={report.kinds} />
    </section>
  );
}

function StressFailures({ kinds }: { kinds: Kind[] }) {
  const failed = kinds.filter((kind) => (kind.failed?.length ?? 0) > 0);
  if (failed.length === 0) return <p className="muted small">No rewritten case failed its expected answer.</p>;
  return (
    <div className="stack">
      {failed.map((kind) => (
        <div key={kind.kind} className="stack">
          <h3>
            {kindLabel(kind.kind)}: {kind.failed.length} failed
          </h3>
          {kind.failed.map((item) => (
            <div key={item.case} className="evaluation-failure">
              <p className="small">
                <strong className="mono">{item.case}</strong>: {item.note}
              </p>
              {(item.events ?? []).map((event) => (
                <p key={event.event} className="small muted">
                  {event.text} - extracted{" "}
                  {(event.facts ?? []).map((fact) => fact.type).join(", ") || "nothing"}
                </p>
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function Voice({ report }: { report: Bundle["voice"] }) {
  return (
    <section className="panel evaluation-panel" data-testid="evaluation-voice">
      <div className="panel-head">
        <h2>Voice notes with site noise</h2>
        {report ? <span className="panel-aside">{report.complete ? "measurement complete" : "measurement running"}</span> : null}
      </div>
      {!report || !completeVoice(report) ? (
        <p className="muted">
          {report
            ? "Not run yet: the committed voice report is incomplete."
            : "Not run yet: the noise evaluation is blocked by its safe-failure condition, so there is no committed report to show. No number is shown instead of one."}
        </p>
      ) : (
        <>
          <p className="evaluation-run small">
            Speech evaluation run{" "}
            <span className="num">{report.meta.when}</span>
          </p>
          {report.scope && <p className="muted small" data-testid="evaluation-voice-scope">{report.scope}</p>}
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Added noise</th>
                  <th className="num">Clips</th>
                  <th className="num">Keys kept</th>
                  <th className="num">Same facts</th>
                  <th className="num">Safe failures</th>
                  <th className="num">Wrong critical facts</th>
                </tr>
              </thead>
              <tbody>
                {report.levels.map((level) => (
                  <tr key={level.added_snr_db} data-testid="evaluation-level" data-snr={level.added_snr_db}>
                    <td className="num">{level.added_snr_db} dB</td>
                    <td className="num">{level.n}</td>
                    <td className="num">{level.keys_retained}</td>
                    <td className="num">{level.same_facts}</td>
                    <td className="num">{level.safe_failures}</td>
                    <td className="num">{level.wrong_critical_facts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Limitations({ bundle }: { bundle: Bundle }) {
  const seen = new Set<string>();
  const rows: { source: string; text: string }[] = [];
  const add = (source: string, lines: string[] | undefined) => {
    for (const line of lines ?? []) {
      if (seen.has(line)) continue;
      seen.add(line);
      rows.push({ source, text: line });
    }
  };
  add("detection", bundle.pipeline?.limitations);
  add("stress test", bundle.stress?.limitations);
  add("voice noise", bundle.voice?.limitations);
  return (
    <section className="panel evaluation-panel" data-testid="evaluation-limitations">
      <h2>What this does not test</h2>
      {rows.length === 0 ? (
        <p className="muted">The reports state no limitation.</p>
      ) : (
        <ul className="evaluation-limits">
          {rows.map((row) => (
            <li key={row.text}>
              <span className="muted small">{row.source}</span>
              <span>{row.text}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Cases({ report }: { report: Bundle["pipeline"] }) {
  if (!report) return null;
  const cases = report.cases ?? [];
  return (
    <section className="panel evaluation-panel" data-testid="evaluation-cases">
      <div className="panel-head">
        <h2>Cases</h2>
        <span className="panel-aside">
          {cases.filter((item) => item.passed).length} ok of {cases.length}
        </span>
      </div>
      <ul className="evaluation-case-list">
        {cases.map((item) => (
          <li key={item.id} data-testid="evaluation-case" data-status={item.passed ? "ok" : "failed"}>
            <div className="row">
              <strong className="mono">{item.id}</strong>
              <span className={item.passed ? "evaluation-ok" : "evaluation-bad"}>{item.passed ? "ok" : "failed"}</span>
            </div>
            <p className="muted small">{item.note}</p>
            {!item.passed && <CaseFailure item={item} />}
          </li>
        ))}
      </ul>
    </section>
  );
}

function CaseFailure({ item }: { item: Case }) {
  return (
    <div className="evaluation-failure small">
      {(item.errors ?? []).map((message) => (
        <p key={message} className="evaluation-bad">
          {message}
        </p>
      ))}
      {(item.missed ?? []).map((missed) => (
        <p key={`m-${missed.type}`}>Expected {humanize(missed.type)} was not raised.</p>
      ))}
      {(item.false_alarms ?? []).map((alarm) => (
        <p key={`f-${alarm.flag_id}`}>
          {humanize(alarm.type)} was raised without being expected ({alarm.flag_id}).
        </p>
      ))}
    </div>
  );
}

function kindLabel(kind: string) {
  const labels: Record<string, string> = {
    clean: "Clean wording",
    site_slang: "Site slang",
    typos: "Typos",
    mixed_language: "Mixed language",
    asr: "Speech-to-text wording",
    long: "Long messages",
  };
  return labels[kind] ?? humanize(kind);
}

function humanize(value: string) {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
