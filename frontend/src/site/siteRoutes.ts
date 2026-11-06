// Public pages and the Studio share one origin (ADR 0058). Hosting must serve
// index.html for every path below (an SPA fallback).
export type Route = "home" | "how" | "join" | "studio";

export function routeFor(pathname: string, search: string): Route {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/how-it-works") return "how";
  if (path === "/join") return "join";
  if (path === "/studio" || path.startsWith("/studio/")) return "studio";
  const query = new URLSearchParams(search);
  // Links made before the public pages (?project=…) and sign-in callbacks open the Studio.
  const callback = query.has("code") && query.has("state");
  if (path === "/" && (query.has("project") || query.has("thread") || callback)) return "studio";
  return "home";
}

/** Only same-origin paths may be a return target after signing in. */
export function safeReturn(target: unknown): string {
  return typeof target === "string" && target.startsWith("/") && !target.startsWith("//") ? target : "/studio";
}
