import { useCallback, useLayoutEffect, useRef } from "react";
import { ApiError } from "../lib/api";

export type ReleaseRun = <T>(channel: string, operation: (signal: AbortSignal) => Promise<T>,
  apply: (value: T) => void, fail: (error: unknown) => void, settled?: () => void) => Promise<void>;

export function releaseErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "The studio could not reach the server. Check your connection and try again.";
}

// Each mounted project dialog owns one request scope, shared with its children.
// Late callbacks, including Blob verification, cannot act after navigation,
// revocation, invalidation or a newer request on the same channel.
export function useReleaseRequests(onAccessLost: () => void) {
  const scope = useRef({ alive: true, requests: new Map<string, AbortController>() });
  const lost = useRef(onAccessLost); lost.current = onAccessLost;
  const cancel = useCallback((channel: string) => {
    scope.current.requests.get(channel)?.abort(); scope.current.requests.delete(channel);
  }, []);
  const invalidate = useCallback(() => {
    const current = scope.current; current.alive = false;
    for (const request of current.requests.values()) request.abort();
    current.requests.clear();
  }, []);
  useLayoutEffect(() => {
    const current = scope.current; current.alive = true;
    return () => {
      invalidate();
    };
  }, [invalidate]);
  // `apply` must stay synchronous; put all async work in `operation`.
  const run = useCallback<ReleaseRun>(async (channel, operation, apply, fail, settled) => {
    const current = scope.current;
    if (!current.alive) return;
    current.requests.get(channel)?.abort();
    const request = new AbortController(); current.requests.set(channel, request);
    const valid = () => current.alive && !request.signal.aborted && current.requests.get(channel) === request;
    try {
      const result = await operation(request.signal);
      if (valid()) apply(result);
    } catch (error) {
      if (!valid() || (error instanceof Error && error.name === "AbortError")) return;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        invalidate(); lost.current();
      } else fail(error);
    } finally {
      if (valid()) { current.requests.delete(channel); settled?.(); }
    }
  }, [invalidate]);
  return { run, cancel, invalidate };
}
