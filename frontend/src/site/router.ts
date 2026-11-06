import { useSyncExternalStore } from "react";
import { routeFor, type Route } from "./siteRoutes";

// A path router without a dependency: links push history entries and every
// subscriber re-reads the location.
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());
window.addEventListener("popstate", notify);

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function navigate(path: string, options: { replace?: boolean } = {}): void {
  if (options.replace) history.replaceState(history.state, "", path);
  else history.pushState(null, "", path);
  if (!options.replace) window.scrollTo({ top: 0 });
  notify();
}

export function useRoute(): Route {
  const location = useSyncExternalStore(subscribe, () => window.location.pathname + window.location.search);
  const url = new URL(location, window.location.origin);
  return routeFor(url.pathname, url.search);
}

/** Same-origin link that navigates without reloading the page. */
export function linkProps(path: string) {
  return {
    href: path,
    onClick: (event: { preventDefault: () => void; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; button: number }) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      navigate(path);
    },
  };
}
