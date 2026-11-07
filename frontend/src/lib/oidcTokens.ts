// What differs between sign-in providers, kept apart from React so it can be tested.

export type BearerKind = "access_token" | "id_token";

interface Tokens {
  access_token: string;
  id_token?: string;
  expired?: boolean;
}

/** Most providers put the audience and email in the access token. Cognito's access token has
 * neither unless you pay for its feature plan, but its ID token has both. */
export function bearerKind(configured: string | undefined): BearerKind {
  return configured === "id_token" ? "id_token" : "access_token";
}

export function bearerToken(user: Tokens | null | undefined, kind: BearerKind): string | null {
  if (!user || user.expired) return null;
  return kind === "id_token" ? (user.id_token ?? null) : user.access_token;
}

/** Cognito publishes no end-session endpoint, so its sign-out page has to be named directly. */
export function logoutAddress(
  configured: string | undefined,
  clientId: string | undefined,
  origin: string,
): string | null {
  if (!configured || !clientId) return null;
  const address = new URL(configured);
  address.searchParams.set("client_id", clientId);
  address.searchParams.set("logout_uri", origin);
  return address.toString();
}

export function displayName(profile: { name?: unknown; email?: unknown } | undefined): string | null {
  if (typeof profile?.name === "string") return profile.name;
  return typeof profile?.email === "string" ? profile.email : null;
}
