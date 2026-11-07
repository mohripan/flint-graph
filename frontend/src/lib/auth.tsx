import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { UserManager, type User } from "oidc-client-ts";
import { navigate } from "../site/router";
import { safeReturn } from "../site/siteRoutes";
import { bearerKind, bearerToken, displayName, logoutAddress } from "./oidcTokens";

type AuthMode = "dev" | "oidc";

interface AuthContextValue {
  mode: AuthMode;
  loading: boolean;
  authenticated: boolean;
  userName: string | null;
  /** Signs in, then returns to `returnTo` (default: the current page). */
  signIn: (returnTo?: string) => Promise<void>;
  signOut: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const authMode = (import.meta.env.VITE_FLINT_GRAPH_AUTH_MODE ?? "dev") as AuthMode;
const bearer = bearerKind(import.meta.env.VITE_FLINT_GRAPH_OIDC_BEARER);

function createUserManager(): UserManager | null {
  if (authMode !== "oidc") return null;
  const authority = import.meta.env.VITE_FLINT_GRAPH_OIDC_AUTHORITY;
  const clientId = import.meta.env.VITE_FLINT_GRAPH_OIDC_CLIENT_ID;
  if (!authority || !clientId) return null;
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: window.location.origin,
    post_logout_redirect_uri: window.location.origin,
    response_type: "code",
    scope: "openid profile email",
  });
}

const userManager = createUserManager();

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(authMode === "oidc");
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (authMode !== "oidc" || !userManager) return;
    let alive = true;
    async function loadUser() {
      try {
        const isCallback =
          window.location.search.includes("code=") &&
          window.location.search.includes("state=");
        if (isCallback) {
          const callbackUser = await userManager!.signinRedirectCallback();
          const state = callbackUser.state as { returnTo?: unknown } | undefined;
          navigate(safeReturn(state?.returnTo), { replace: true });
          if (alive) setUser(callbackUser);
          return;
        }
        const current = await userManager!.getUser();
        if (alive) setUser(current && !current.expired ? current : null);
      } finally {
        if (alive) setLoading(false);
      }
    }
    void loadUser();
    return () => {
      alive = false;
    };
  }, []);

  const signIn = useCallback(async (returnTo?: string) => {
    if (authMode === "dev") return;
    if (!userManager) throw new Error("OIDC is not configured.");
    const here = window.location.pathname + window.location.search;
    await userManager.signinRedirect({ state: { returnTo: returnTo ?? here } });
  }, []);

  const signOut = useCallback(async () => {
    if (authMode === "dev") return;
    if (!userManager) return;
    const leaveTo = logoutAddress(
      import.meta.env.VITE_FLINT_GRAPH_OIDC_LOGOUT_URL,
      import.meta.env.VITE_FLINT_GRAPH_OIDC_CLIENT_ID,
      window.location.origin,
    );
    if (leaveTo) {
      await userManager.removeUser();
      window.location.assign(leaveTo);
      return;
    }
    await userManager.signoutRedirect();
  }, []);

  const getAccessToken = useCallback(async () => {
    if (authMode === "dev") return null;
    const current = user ?? (userManager ? await userManager.getUser() : null);
    return bearerToken(current, bearer);
  }, [user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      mode: authMode,
      loading,
      authenticated: authMode === "dev" || Boolean(user && !user.expired),
      userName: authMode === "dev" ? "Local Developer" : displayName(user?.profile),
      signIn,
      signOut,
      getAccessToken,
    }),
    [getAccessToken, loading, signIn, signOut, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
