import { useCallback, useEffect, useRef, useState } from "react";
import App from "../App";
import { AuthGate } from "../components/WorkspaceGate";
import { Spinner } from "../components/ui";
import { ApiError, api, setResponseObserver, type AccessStatus } from "../lib/api";
import { useAuth } from "../lib/auth";
import { WorkspaceProvider } from "../lib/workspace";
import { AccessContext, AccessRefreshContext } from "./accessContext";
import { paidRequest, usageProblem } from "./creditsModel";
import { navigate } from "./router";

// An API from before ADR 0058 has no access routes: it is open to every signed-in user.
const OPEN: AccessStatus = {
  mode: "open", has_access: true, is_admin: false, status: "none", email: null, display_name: null,
  limits: null, usage: { image: { day: 0, total: 0 }, voice: { day: 0, total: 0 }, assistant: { day: 0, total: 0 },
    release: { day: 0, total: 0 }, training: { day: 0, total: 0 } }, email_invitation: false,
  credits: null, unlimited: true,
};

export function StudioRoute() {
  const auth = useAuth();
  const [status, setStatus] = useState<AccessStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reloading = useRef<number | null>(null);

  useEffect(() => {
    if (auth.loading || !auth.authenticated) return;
    let alive = true;
    api.accessMe().then(
      next => {
        if (!alive) return;
        if (next.has_access) setStatus(next);
        else navigate("/join", { replace: true });
      },
      failure => {
        if (!alive) return;
        if (failure instanceof ApiError && failure.status === 404) setStatus(OPEN);
        else setError("The Studio's server can't be reached right now. Try again in a moment.");
      },
    );
    return () => { alive = false; };
  }, [auth.loading, auth.authenticated]);

  // Several paid requests in a row reload the balance once.
  const refresh = useCallback(() => {
    if (reloading.current !== null) window.clearTimeout(reloading.current);
    reloading.current = window.setTimeout(() => {
      reloading.current = null;
      api.accessMe().then(next => { if (next.has_access) setStatus(next); }, () => undefined);
    }, 300);
  }, []);

  const metered = status?.mode === "invite";
  useEffect(() => {
    if (!metered) return;
    setResponseObserver(seen => {
      if (seen.path.startsWith("/v1/access/")) return;
      if (usageProblem(seen.problemType) || (seen.status < 300 && paidRequest(seen.method, seen.path))) refresh();
    });
    return () => setResponseObserver(null);
  }, [metered, refresh]);

  if (auth.loading) return <div className="flex min-h-full items-center justify-center" />;
  if (!auth.authenticated) return <AuthGate />;
  if (error) {
    return <div className="flex min-h-full items-center justify-center p-6">
      <p role="alert" className="max-w-md rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
    </div>;
  }
  if (!status) {
    return <div className="flex min-h-full items-center justify-center" role="status" aria-label="Opening the Studio">
      <Spinner className="h-6 w-6" />
    </div>;
  }
  return (
    <AccessContext.Provider value={status}>
      <AccessRefreshContext.Provider value={refresh}>
        <WorkspaceProvider>
          <App />
        </WorkspaceProvider>
      </AccessRefreshContext.Provider>
    </AccessContext.Provider>
  );
}
