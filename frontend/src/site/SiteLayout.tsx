import type { ReactNode } from "react";
import { Logo } from "../components/WorkspaceGate";
import { useAuth } from "../lib/auth";
import { linkProps } from "./router";
import "./site.css";

// Header and footer for the public pages: no sign-in or API call is needed to view them.
export function SiteLayout({ children, current }: { children: ReactNode; current: "home" | "how" | "join" }) {
  const auth = useAuth();
  const signedIn = auth.mode === "dev" || auth.authenticated;
  const link = (path: string, label: string, active: boolean) => (
    <a {...linkProps(path)} aria-current={active ? "page" : undefined}
      className={`rounded-lg px-3 py-2 text-sm font-medium transition ${active ? "text-white" : "text-slate-300 hover:text-white"}`}>
      {label}
    </a>
  );
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-[#0d1624]/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <a {...linkProps("/")} className="flex items-center gap-3" aria-label="FlintGraph home">
            <Logo className="h-9 w-9" />
            <span className="site-serif text-lg font-semibold text-white">FlintGraph</span>
          </a>
          <nav aria-label="Site" className="flex flex-wrap items-center gap-1">
            {link("/how-it-works", "How it works", current === "how")}
            {link("/join", "Join", current === "join")}
            <a {...linkProps("/studio")}
              className="ml-1 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-900 shadow-xs transition hover:bg-amber-50">
              {signedIn ? "Open Studio" : "Sign in"}
            </a>
          </nav>
        </div>
      </header>
      <main className="flex flex-1 flex-col [&>*:last-child]:flex-1">{children}</main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-8 text-sm text-slate-500 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo className="h-7 w-7" />
            <span>FlintGraph · a studio for visual novels</span>
          </div>
          <nav aria-label="Footer" className="flex gap-4">
            <a {...linkProps("/how-it-works")} className="hover:text-slate-800">How it works</a>
            <a {...linkProps("/join")} className="hover:text-slate-800">Join with an invitation</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

export function Screenshot({ src, alt, className = "" }: { src: string; alt: string; className?: string }) {
  return <img src={src} alt={alt} loading="lazy" decoding="async" className={`w-full rounded-xl bg-slate-200 ${className}`} />;
}
