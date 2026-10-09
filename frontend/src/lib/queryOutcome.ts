import type { QueryRunResponse } from "./types";

export function queryFailureMessage(
  run: Pick<QueryRunResponse, "status" | "error_message">,
): string | null {
  if (run.status === "failed") {
    return run.error_message || "The query could not be answered. Check provider settings in Setup.";
  }
  if (run.status === "cancelled") {
    return "The query was cancelled before an answer was finalized.";
  }
  if (run.status !== "completed") {
    return "The connection closed before the query finished. Check query history for its status.";
  }
  return null;
}
