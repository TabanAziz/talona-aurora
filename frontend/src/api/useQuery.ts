import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

export type ForcedState = "loading" | "empty" | "error" | null;

export function useForcedState(): ForcedState {
  const [params] = useSearchParams();
  const value = params.get("state");
  return value === "loading" || value === "empty" || value === "error" ? value : null;
}

export interface Query<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

interface Options<T> {
  /** Refetch interval in ms, so events ingested elsewhere show up without a reload. */
  poll?: number;
  /** What `?state=empty` shows for this query. Without it the forced empty state is ignored. */
  empty?: T;
  /** Skip the request, for queries that depend on another one. */
  skip?: boolean;
}

/**
 * One way to load data. `?state=loading|empty|error` forces that state without a request,
 * so the layout checker sees no failed network call in the forced error state.
 */
export function useQuery<T>(fetcher: () => Promise<T>, deps: unknown[], options: Options<T> = {}): Query<T> {
  const forced = useForcedState();
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const { poll, skip } = options;
  const active = !skip && forced === null;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const load = () =>
      fetcherRef.current().then(
        (value) => {
          if (cancelled) return;
          setData(value);
          setError(null);
          setLoading(false);
        },
        (reason: unknown) => {
          if (cancelled) return;
          setError(reason instanceof Error ? reason.message : "Something went wrong.");
          setLoading(false);
        },
      );
    load();
    const timer = poll ? window.setInterval(load, poll) : undefined;
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
    // deps are the caller's cache key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, poll, tick, ...deps]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((n) => n + 1);
  }, []);

  if (forced === "loading") return { data: undefined, error: null, loading: true, reload };
  if (forced === "error") {
    return { data: undefined, error: "The server did not answer (forced error state).", loading: false, reload };
  }
  if (forced === "empty" && options.empty !== undefined) {
    return { data: options.empty, error: null, loading: false, reload };
  }
  if (skip) return { data: undefined, error: null, loading: false, reload };
  // a failed background refetch keeps the last good data on screen
  if (data !== undefined) return { data, error: null, loading: false, reload };
  return { data, error, loading, reload };
}
