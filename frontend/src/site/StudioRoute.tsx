import { useEffect, useState } from "react";
import App from "../App";
import { AuthGate } from "../components/WorkspaceGate";
import { Spinner } from "../components/ui";
import { ApiError, api, type AccessStatus } from "../lib/api";
import { useAuth } from "../lib/auth";
import { WorkspaceProvider } from "../lib/workspace";
import { AccessContext } from "./accessContext";
import { navigate } from "./router";

// An API from before ADR 0058 has no access routes: it is open to every signed-in user.
const OPEN: AccessStatus = {
  mode: "open", has_access: true, is_admin: false, status: "none", email: null, display_name: null,
  limits: null, usage: { image: { day: 0, total: 0 }, voice: { day: 0, total: 0 }, assistant: { day: 0, total: 0 },
    release: { day: 0, total: 0 }, training: { day: 0, total: 0 } }, email_invitation: false,
};

export function StudioRoute() {
  const auth = useAuth();
  const [status, setStatus] = useState<AccessStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      <WorkspaceProvider>
        <App />
      </WorkspaceProvider>
    </AccessContext.Provider>
  );
}
