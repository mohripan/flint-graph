import { useEffect, useRef, useState } from "react";
import { acceptPreviewMessage, previewOrigin } from "./previewProtocol";
import type { PreviewPhase } from "./previewProtocol";
import { StudioDialog } from "./StudioDialog";
import type { NarrativeRevision } from "./types";

export function PreviewDialog({ revision, onClose }: { revision: NarrativeRevision; onClose: () => void }) {
  const iframe = useRef<HTMLIFrameElement>(null);
  const [nonce] = useState(() => [...crypto.getRandomValues(new Uint8Array(32))].map(value => value.toString(16).padStart(2, "0")).join(""));
  const [phase, setPhase] = useState<PreviewPhase>("waiting");
  const [error, setError] = useState<string | null>(null);
  let origin = "";
  try { origin = previewOrigin(import.meta.env.VITE_FLINT_GRAPH_PREVIEW_ORIGIN ?? "", location.origin); }
  catch { origin = ""; }
  useEffect(() => {
    if (!origin) return;
    let current: PreviewPhase = "waiting";
    const timeout = window.setTimeout(() => { current = "error"; setPhase("error"); setError("The story player did not respond. Close playtest and retry."); }, 45000);
    const receive = (event: MessageEvent) => {
      const child = iframe.current?.contentWindow;
      if (!child) return;
      const message = acceptPreviewMessage(event, { window: child, origin, nonce,
        revision: revision.id, hash: revision.content_hash }, current);
      if (message === "ready") {
        current = "loading"; setPhase(current);
        child.postMessage({ protocol: "flint-preview", version: 1, nonce, type: "load-snapshot",
          revision_id: revision.id, content_hash: revision.content_hash, story_json: revision.story_json, notices: revision.notices }, origin);
      } else if (message === "loaded" || message === "error") {
        current = message; setPhase(message); window.clearTimeout(timeout);
        if (message === "error") setError("The saved snapshot could not be validated by the story player.");
      } else if (message === "close") onClose();
    };
    window.addEventListener("message", receive);
    return () => { window.clearTimeout(timeout); window.removeEventListener("message", receive); };
  }, [origin, nonce, revision, onClose]);
  // QA is explicitly opt-in, read-only, and uses the shared runtime's existing probe.
  const qa = new URLSearchParams(location.search).get("qa") === "1" ? "?qa=1" : "";
  return <StudioDialog label={`Playtest revision ${revision.revision_number}`} onClose={onClose}>
    <div className="studio-preview-body"><header className="studio-section-heading">
      <div><h2>Playtest · revision {revision.revision_number}</h2><p>Saved snapshot · progress stays in memory · Escape returns to the studio</p></div>
      <button type="button" className="studio-secondary" onClick={onClose}>Close playtest</button></header>
      {(!origin || error) ? <p role="alert" className="studio-error">{error ?? "Configure a trusted preview on a separate host to play this revision."}</p>
        : <><p role="status" className="studio-preview-status">{phase === "loaded" ? "Playing saved revision" : "Starting the story player…"}</p>
          <iframe ref={iframe} src={`${origin}/index.html${qa}#${nonce}`} title="Saved story playtest"
            sandbox="allow-scripts allow-same-origin" referrerPolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'" /></>}
    </div>
  </StudioDialog>;
}
