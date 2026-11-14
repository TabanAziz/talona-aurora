import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Authorization, type Autonomy as AutonomyData, type AutonomySuggestion } from "../../api/client";
import { useForcedState, useQuery } from "../../api/useQuery";
import { Badge } from "../../components/Badge";
import { formatTime } from "../../components/format";
import { Empty, ErrorState, Loading } from "../../components/States";
import { GRANTED_BY, REVOKED_BY, applicationsText, decisionLinks, endText, isActive } from "./grants";
import "./autonomy.css";

type Action = { kind: "grant"; suggestionId: string } | { kind: "revoke"; authorizationId: string };

interface Failure {
  message: string;
  retry: Action;
}

export function Autonomy() {
  const forced = useForcedState();
  const autonomy = useQuery(api.autonomy, []);
  const project = useQuery(api.project, []);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: Action) {
    setBusy(true);
    setFailure(null);
    try {
      if (action.kind === "grant") {
        await api.grantAutonomy({ suggestion_id: action.suggestionId, granted_by: GRANTED_BY });
      } else {
        await api.revokeAutonomy(action.authorizationId, { revoked_by: REVOKED_BY });
      }
      setConfirm(null);
      autonomy.reload();
    } catch (error) {
      // Nothing on this page changed: the list still shows what the server last said, and Retry repeats the request.
      setFailure({ message: error instanceof Error ? error.message : "The request failed.", retry: action });
    } finally {
      setBusy(false);
    }
  }

  if (forced === "empty") {
    return <Empty>Aurora has no autonomy yet. It earns it from three decisions of the same kind.</Empty>;
  }
  if (autonomy.error) return <ErrorState message={autonomy.error} onRetry={autonomy.reload} />;
  if (autonomy.loading || autonomy.data === undefined) return <Loading rows={6} />;

  const data = autonomy.data;
  const noSuggestions = (data.suggestions ?? []).length === 0;
  const noAuthorizations = (data.authorizations ?? []).length === 0;
  if (noSuggestions && noAuthorizations) {
    return (
      <Empty>
        Aurora has no autonomy yet. It can earn the right to hold work by itself after three decisions of the same
        kind, and only a person can grant it. <Link to="/">Back to Today</Link>.
      </Empty>
    );
  }
  return (
    <AutonomyBody
      data={data}
      demoData={project.data?.demo_data ?? false}
      confirm={confirm}
      failure={failure}
      busy={busy}
      onAsk={setConfirm}
      onCancel={() => setConfirm(null)}
      onRun={run}
      onRetry={() => failure && void run(failure.retry)}
    />
  );
}

interface BodyProps {
  data: AutonomyData;
  demoData: boolean;
  confirm: Action | null;
  failure: Failure | null;
  busy: boolean;
  onAsk: (action: Action) => void;
  onCancel: () => void;
  onRun: (action: Action) => Promise<void>;
  onRetry: () => void;
}

function AutonomyBody({ data, demoData, confirm, failure, busy, onAsk, onCancel, onRun, onRetry }: BodyProps) {
  const authorizations = data.authorizations ?? [];
  const suggestions = data.suggestions ?? [];
  const active = authorizations.filter(isActive);
  const ended = authorizations.filter((authorization) => !isActive(authorization));
  return (
    <div className="autonomy" data-testid="autonomy-view">
      <div className="page-head">
        <div>
          <h1>Autonomy</h1>
          <p className="muted small">What Aurora may do alone, and how you take it back.</p>
        </div>
        <div className="row">
          {demoData && (
            <span data-testid="autonomy-demo">

            </span>
          )}
          <span className="muted small">
            <span className="num">{data.automatic_holds_today}</span> of{" "}
            <span className="num">{data.daily_limit}</span> automatic holds today
          </span>
        </div>
      </div>

      <p className="panel autonomy-intro">
        Aurora may hold work by itself, and only under an authorization you grant. Releasing, rescheduling and
        dismissing always stay with you, and a hold already made stays held until you release it.
      </p>

      {failure && (
        <div className="panel autonomy-failure" role="alert" data-testid="autonomy-error">
          <p>
            <strong>Nothing changed.</strong> {failure.message}
          </p>
          <button type="button" className="button" data-testid="autonomy-retry" disabled={busy} onClick={onRetry}>
            Retry
          </button>
        </div>
      )}

      <section className="panel autonomy-card" aria-labelledby="autonomy-suggestions-heading">
        <div className="panel-head">
          <h2 id="autonomy-suggestions-heading">Earned and not granted yet</h2>
          <span className="panel-aside">
            {suggestions.length === 0
              ? "Nothing to grant"
              : `${suggestions.length} suggestion${suggestions.length === 1 ? "" : "s"}`}
          </span>
        </div>
        {suggestions.length === 0 ? (
          <p className="muted">No suggestion. Aurora suggests a grant after three decisions of the same kind.</p>
        ) : (
          <ul className="autonomy-list">
            {suggestions.map((suggestion) => (
              <SuggestionRow
                key={suggestion.id}
                suggestion={suggestion}
                asking={confirm?.kind === "grant" && confirm.suggestionId === suggestion.id}
                busy={busy}
                onAsk={onAsk}
                onCancel={onCancel}
                onRun={onRun}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="panel autonomy-card" aria-labelledby="autonomy-active-heading">
        <div className="panel-head">
          <h2 id="autonomy-active-heading">Active authorizations</h2>
          <span className="panel-aside">{active.length === 1 ? "1 active" : `${active.length} active`}</span>
        </div>
        {active.length === 0 ? (
          <p className="muted">No active authorization. Aurora asks before every hold.</p>
        ) : (
          <ul className="autonomy-list">
            {active.map((authorization) => (
              <AuthorizationRow
                key={authorization.id}
                authorization={authorization}
                asking={confirm?.kind === "revoke" && confirm.authorizationId === authorization.id}
                busy={busy}
                onAsk={onAsk}
                onCancel={onCancel}
                onRun={onRun}
              />
            ))}
          </ul>
        )}
      </section>

      {ended.length > 0 && (
        <section className="panel autonomy-card" aria-labelledby="autonomy-ended-heading">
          <div className="panel-head">
            <h2 id="autonomy-ended-heading">Given back</h2>
            <span className="panel-aside">{ended.length === 1 ? "1 authorization" : `${ended.length} authorizations`}</span>
          </div>
          <ul className="autonomy-list">
            {ended.map((authorization) => (
              <AuthorizationRow
                key={authorization.id}
                authorization={authorization}
                asking={false}
                busy={busy}
                onAsk={onAsk}
                onCancel={onCancel}
                onRun={onRun}
              />
            ))}
          </ul>
        </section>
      )}

      <p className="muted small">
        Every application above is a decision in the record, made by Aurora under the authorization you granted.
        An authorization applies to future flags only.
      </p>
    </div>
  );
}

interface RowProps {
  asking: boolean;
  busy: boolean;
  onAsk: (action: Action) => void;
  onCancel: () => void;
  onRun: (action: Action) => Promise<void>;
}

function SuggestionRow({ suggestion, asking, busy, onAsk, onCancel, onRun }: RowProps & { suggestion: AutonomySuggestion }) {
  return (
    <li
      className="autonomy-item"
      data-testid="autonomy-suggestion"
      data-suggestion-id={suggestion.id}
      data-flag-type={suggestion.flag_type}
    >
      <div className="autonomy-item-head">
        <p className="autonomy-statement">{suggestion.statement}</p>
        <Badge>{suggestion.flag_type.replace(/_/g, " ")}</Badge>
      </div>
      <p className="muted small">
        Last of three decisions, <span className="num">{formatTime(suggestion.last_decided_at)}</span>
      </p>
      <ul className="autonomy-decisions small">
        {decisionLinks(suggestion).map((link) => (
          <li key={link.decisionId}>
            {link.href ? (
              <Link to={link.href} data-testid="autonomy-decision" title={link.decisionId}>
                {link.decisionId}
              </Link>
            ) : (
              <span className="num" data-testid="autonomy-decision">
                {link.decisionId}
              </span>
            )}{" "}
            on {link.flagId || "an unknown flag"}
          </li>
        ))}
      </ul>
      {asking ? (
        <div className="autonomy-confirm" role="group" aria-label="Confirm this grant">
          <p>Grant Aurora the right to hold this kind of case by itself?</p>
          <div className="row">
            <button
              type="button"
              className="button button-primary"
              data-testid="autonomy-confirm"
              disabled={busy}
              onClick={() => void onRun({ kind: "grant", suggestionId: suggestion.id })}
            >
              {busy ? "Granting..." : "Grant it"}
            </button>
            <button type="button" className="button" data-testid="autonomy-cancel" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="button autonomy-action"
          data-testid="autonomy-grant"
          disabled={busy}
          onClick={() => onAsk({ kind: "grant", suggestionId: suggestion.id })}
        >
          Grant this
        </button>
      )}
    </li>
  );
}

function AuthorizationRow({ authorization, asking, busy, onAsk, onCancel, onRun }: RowProps & { authorization: Authorization }) {
  const active = isActive(authorization);
  const end = endText(authorization);
  return (
    <li
      className={active ? "autonomy-item" : "autonomy-item autonomy-item-ended"}
      data-testid="autonomy-rule"
      data-status={authorization.status}
      data-authorization-id={authorization.id}
    >
      <div className="autonomy-item-head">
        <p className="autonomy-statement">{authorization.statement}</p>
        <Badge tone={active ? "success" : "neutral"}>{authorization.status}</Badge>
      </div>
      <p className="muted small">
        Granted by {authorization.granted_by} on{" "}
        <span className="num">{formatTime(authorization.granted_at)}</span>
      </p>
      {active && <p className="muted small">{applicationsText(authorization)}</p>}
      {end && <p className="muted small">{end}</p>}
      {(authorization.applications ?? []).length > 0 && (
        <ul className="autonomy-applications small">
          {(authorization.applications ?? []).map((application) => (
            <li key={application.decision_id} data-testid="autonomy-applied">
              <span className="num">{formatTime(application.at)}</span>{" "}
              <Link to={`/flags/${encodeURIComponent(application.flag_id)}`} title={application.decision_id}>
                flag {application.flag_id}
              </Link>{" "}
              <Link
                to={`/flags/${encodeURIComponent(application.flag_id)}`}
                data-testid="autonomy-record"
                title={`Record entry ${application.record_entry_id}`}
              >
                {application.record_entry_id}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {active &&
        (asking ? (
          <div className="autonomy-confirm" role="group" aria-label="Confirm this revocation">
            <p>Aurora stops holding work by itself. Holds already made stay held.</p>
            <div className="row">
              <button
                type="button"
                className="button button-primary"
                data-testid="autonomy-confirm"
                disabled={busy}
                onClick={() => void onRun({ kind: "revoke", authorizationId: authorization.id })}
              >
                {busy ? "Revoking..." : "Revoke it"}
              </button>
              <button type="button" className="button" data-testid="autonomy-cancel" disabled={busy} onClick={onCancel}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="button autonomy-action"
            data-testid="autonomy-revoke"
            disabled={busy}
            onClick={() => onAsk({ kind: "revoke", authorizationId: authorization.id })}
          >
            Revoke
          </button>
        ))}
    </li>
  );
}
