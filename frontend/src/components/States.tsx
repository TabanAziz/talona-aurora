import type { ReactNode } from "react";
import type { Query } from "../api/useQuery";

export function Loading({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="skeleton" role="status" aria-label={label} data-testid="state-loading">
      {Array.from({ length: rows }, (_, i) => (
        <div className="skeleton-row" key={i} />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="state state-empty" data-testid="state-empty">
      {children}
    </p>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="state state-error" role="alert" data-testid="state-error">
      <p>
        <strong>Could not load this.</strong> {message}
      </p>
      <button type="button" className="button" onClick={onRetry} data-testid="state-retry">
        Retry
      </button>
    </div>
  );
}

export function Unavailable() {
  return <span className="muted">unavailable</span>;
}

interface AsyncProps<T> {
  query: Query<T>;
  rows?: number;
  /** Sentence shown when the data is an empty list. */
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}

/** The four states of every view in one place: loading, error, empty, content. */
export function Async<T>({ query, rows, empty, children }: AsyncProps<T>) {
  if (query.error) return <ErrorState message={query.error} onRetry={query.reload} />;
  if (query.loading || query.data === undefined) return <Loading rows={rows} />;
  if (empty !== undefined && Array.isArray(query.data) && query.data.length === 0) return <Empty>{empty}</Empty>;
  return <>{children(query.data)}</>;
}
