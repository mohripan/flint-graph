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

type AuthMode = "dev" | "oidc";

interface AuthContextValue {
  mode: AuthMode;
  loading: boolean;
  authenticated: boolean;
  userName: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const authMode = (import.meta.env.VITE_FLINT_GRAPH_AUTH_MODE ?? "dev") as AuthMode;

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
          window.history.replaceState({}, document.title, window.location.pathname);
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

  const signIn = useCallback(async () => {
    if (authMode === "dev") return;
    if (!userManager) throw new Error("OIDC is not configured.");
    await userManager.signinRedirect();
  }, []);

  const signOut = useCallback(async () => {
    if (authMode === "dev") return;
    if (userManager) await userManager.signoutRedirect();
  }, []);

  const getAccessToken = useCallback(async () => {
    if (authMode === "dev") return null;
    const current = user ?? (userManager ? await userManager.getUser() : null);
    return current && !current.expired ? current.access_token : null;
  }, [user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      mode: authMode,
      loading,
      authenticated: authMode === "dev" || Boolean(user && !user.expired),
      userName:
        authMode === "dev"
          ? "Local Developer"
          : typeof user?.profile.name === "string"
            ? user.profile.name
            : null,
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
