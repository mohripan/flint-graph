import { lazy, Suspense, useEffect } from "react";
import { setAccessRequiredHandler, setAccessTokenProvider } from "../lib/api";
import { useAuth } from "../lib/auth";
import { HomePage } from "./HomePage";
import { HowItWorksPage } from "./HowItWorksPage";
import { JoinPage } from "./JoinPage";
import { navigate, useRoute } from "./router";

// The Studio is a separate download, so the public pages stay light.
const StudioRoute = lazy(() => import("./StudioRoute").then(module => ({ default: module.StudioRoute })));

const TITLES = {
  home: "FlintGraph · a studio for visual novels",
  how: "How it works · FlintGraph",
  join: "Join · FlintGraph",
  studio: "FlintGraph Studio",
} as const;

export function SiteRoot() {
  const auth = useAuth();
  const route = useRoute();

  // Re-set after any route change: the Studio's workspace provider clears it on unmount.
  useEffect(() => {
    setAccessTokenProvider(() => auth.getAccessToken());
  }, [auth, route]);
  useEffect(() => {
    setAccessRequiredHandler(() => navigate("/join"));
    return () => setAccessRequiredHandler(null);
  }, []);
  useEffect(() => {
    document.title = TITLES[route];
  }, [route]);
  // Links made before the public pages (/?project=…) move to /studio once any sign-in finished.
  useEffect(() => {
    if (route === "studio" && window.location.pathname === "/" && !auth.loading) {
      navigate("/studio" + window.location.search, { replace: true });
    }
  }, [route, auth.loading]);

  switch (route) {
    case "how":
      return <HowItWorksPage />;
    case "join":
      return <JoinPage />;
    case "studio":
      return <Suspense fallback={<div className="flex min-h-full items-center justify-center" />}><StudioRoute /></Suspense>;
    default:
      return <HomePage />;
  }
}
