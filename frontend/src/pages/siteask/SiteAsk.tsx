import { projectApiUrl } from "../../api/workspace";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StartCheck, type StartReason } from "../../api/client";
import { Badge, type Tone } from "../../components/Badge";
import { formatTime, humanize } from "../../components/format";
import type { SiteUnit } from "../site/units";
import "./siteask.css";

const NOTHING_CHANGES = "Asking changes nothing on site: no work starts, no flag is raised and no message is sent.";
const MAX_ANSWERS = 4;

const ALLOWED_TONE: Record<StartCheck["allowed"], Tone> = { yes: "success", no: "danger", unknown: "warning" };

function unitAnswers(answers: StartCheck[], stored: StartCheck[], unit: SiteUnit | null): StartCheck[] {
  if (!unit) return [];
  const taskIds = new Set(unit.tasks.map((task) => task.id));
  const seen = new Set<string>();
  const matches = [...answers, ...stored].filter((answer) => {
    const belongs = answer.unit === unit.unit || (answer.task_id != null && taskIds.has(answer.task_id));
    if (!belongs || seen.has(answer.id)) return false;
    seen.add(answer.id);
    return true;
  });
  return matches.sort((a, b) => b.checked_at.localeCompare(a.checked_at)).slice(0, MAX_ANSWERS);
}

function Reason({ reason }: { reason: StartReason }) {
  const sources = reason.sources ?? [];
  return (
    <li className="siteask-reason" data-testid="siteask-reason" data-kind={reason.kind}>
      <div className="row">
        <Badge tone={reason.blocking ? "danger" : "warning"}>{humanize(reason.kind)}</Badge>
        <span className="small muted">{reason.blocking ? "blocking" : "not blocking"}</span>
        {reason.flag_id && (
          <Link className="siteask-flag small" data-testid="siteask-flag" to={`/flags/${encodeURIComponent(reason.flag_id)}`}>
            Flag {reason.flag_id}
          </Link>
        )}
      </div>
      <p className="small">{reason.text}</p>
      {sources.length > 0 && (
        <ul className="siteask-sources">
          {sources.map((source) => (
            <li key={`${source.event_id}-${source.quote}`}>
              <a
                className="siteask-source small"
                data-testid="siteask-source"
                href={projectApiUrl(`/api/events/${encodeURIComponent(source.event_id)}`)}
                target="_blank"
                rel="noreferrer"
              >
                <span className="num">{source.event_id}</span>: "{source.quote}"{" "}
                <span className="muted">
                  ({source.sender}, {source.channel})
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function SiteAsk({ unit, stored }: { unit: SiteUnit | null; stored: StartCheck[] }) {
  const [name, setName] = useState("Site visitor");
  const [asked, setAsked] = useState<StartCheck[]>([]);
  const [busyTask, setBusyTask] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ task: string; message: string } | null>(null);

  const askedBy = name.trim() || "Site visitor";
  const answers = useMemo(() => unitAnswers(asked, stored, unit), [asked, stored, unit]);

  async function ask(taskId: string) {
    if (!unit || busyTask !== null) return;
    setBusyTask(taskId);
    setFailure(null);
    try {
      const answer = await api.canStart({ asked_by: askedBy, task_id: taskId, unit: unit.unit });
      setAsked((current) => [answer, ...current]);
    } catch (err) {
      setFailure({
        task: taskId,
        message: err instanceof Error ? err.message : "The start check did not answer. Try again.",
      });
    } finally {
      setBusyTask(null);
    }
  }

  return (
    <section className="panel siteask" data-testid="siteask-panel" aria-labelledby="siteask-heading">
      <div className="panel-head">
        <h2 id="siteask-heading">May this start?</h2>
        <span className="panel-aside">{unit ? `Unit ${unit.unit}` : "no unit selected"}</span>
      </div>
      <p className="siteask-note small">{NOTHING_CHANGES}</p>
      <label className="siteask-name" htmlFor="siteask-name">
        Your name
        <input
          id="siteask-name"
          data-testid="siteask-name"
          value={name}
          maxLength={64}
          disabled={busyTask !== null}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      {!unit ? (
        <p className="muted small">Select a unit on the model or in the list to ask whether its planned work may start.</p>
      ) : unit.tasks.length === 0 ? (
        <p className="muted small">No task of the plan is scheduled for unit {unit.unit}.</p>
      ) : (
        <ul className="siteask-tasks">
          {unit.tasks.map((task) => (
            <li className="siteask-task" data-testid="siteask-task" data-task={task.id} key={task.id}>
              <span className="siteask-task-name">{task.name}</span>
              <span className="muted small">
                {task.crew}, {humanize(task.status)}
              </span>
              <button
                type="button"
                className="button"
                data-testid="siteask-ask"
                data-task={task.id}
                disabled={busyTask !== null}
                onClick={() => ask(task.id)}
              >
                {busyTask === task.id ? "Asking…" : "May this start"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {failure && (
        <p className="siteask-error" role="alert" data-testid="siteask-error">
          The start check did not answer for {failure.task}: {failure.message}
        </p>
      )}
      {unit && (
        <>
          <h3>Newest answers</h3>
          {answers.length === 0 ? (
            <p className="muted small">Nobody has asked about this unit yet.</p>
          ) : (
            <ol className="siteask-answers" data-testid="siteask-answers">
              {answers.map((answer) => (
                <li className="siteask-answer" data-testid="siteask-answer" data-allowed={answer.allowed} data-task={answer.task_id ?? ""} key={answer.id}>
                  <div className="row">
                    <Badge tone={ALLOWED_TONE[answer.allowed]} testId="siteask-allowed">
                      {answer.allowed}
                    </Badge>
                    <span className="small">{answer.summary}</span>
                  </div>
                  <p className="muted small num">
                    asked by {answer.asked_by} at {formatTime(answer.checked_at)}
                  </p>
                  {(answer.reasons ?? []).length > 0 && (
                    <ul className="siteask-reasons">
                      {(answer.reasons ?? []).map((reason) => (
                        <Reason reason={reason} key={`${reason.kind}-${reason.text}`} />
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
