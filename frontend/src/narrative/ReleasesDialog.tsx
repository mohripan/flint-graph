import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { api } from "../lib/api";
import type { CarriedVoiceLicenses } from "../lib/api";
import { ReleaseHistory } from "./ReleaseHistory";
import {
  activeRelease, artifactLabel, buildBlocker, buildTargets, formatBytes, mergeReleases, newerRelease, prepareRelease,
  prepareReleaseRetry, readyArtifacts, releaseFailure, releaseStatus, replayedRelease, revisionLabel, scopedRelease,
} from "./releaseModel";
import type { ReleaseIntents } from "./releaseModel";
import { releaseErrorMessage, useReleaseRequests } from "./releaseRequests";
import { StudioDialog } from "./StudioDialog";
import type { ArtifactKind, NarrativeRelease, NarrativeRevision, ReleaseArtifact, ReleaseJob, RevisionSummary } from "./types";

const PAGE = 25, kinds: ArtifactKind[] = ["source", "web", "manifest"];
const historyChannels = ["history:jobs", "history:older", "history:events"];
const mismatch = "The server returned a release for a different project. Refresh releases before continuing.";
function tone(job: ReleaseJob): string {
  return activeRelease(job) ? "active" : job.status === "completed" ? "ready" : job.status === "failed" ? "failed" : "muted";
}
function statusDetail(release: NarrativeRelease): string {
  const { job } = release;
  if (activeRelease(job) && job.cancel_requested) return "Stopping the build at its next safe point.";
  if (job.status === "queued") return "Waiting for a build worker. You can close this window; the build keeps its place.";
  if (job.status === "running") return `Exporting with Godot ${release.build_identity.godot_version}. This usually takes a minute or two.`;
  if (job.status === "completed") return "Every file was verified. Downloads are checked again in your browser before saving.";
  if (job.status === "cancelled") return "This build was cancelled. Retry to build the same saved revision again.";
  return releaseFailure(job.error_code);
}

// Releases are server state: closing or reloading never loses a build. Only an
// item GET is trusted for downloads; every late response re-checks its scope.
// Activated controls use aria-disabled plus guards so keyboard focus stays put.
export function ReleasesDialog({ tenantId, projectId, headId, revision, history, canWrite, dirty, saving,
  intents, scopeRef, onSave, onInspect, onClose, onAccessLost }: {
  tenantId: string; projectId: string; headId: string; revision: NarrativeRevision; history: RevisionSummary[];
  canWrite: boolean; dirty: boolean; saving: boolean; intents: ReleaseIntents;
  scopeRef: MutableRefObject<(() => void) | null>; onSave: () => Promise<NarrativeRevision | null>;
  onInspect: (revisionId: string) => void; onClose: () => void; onAccessLost: () => void;
}) {
  const { run, cancel, invalidate } = useReleaseRequests(onAccessLost);
  // The studio invalidates this whole scope first when access or the project changes.
  useLayoutEffect(() => {
    scopeRef.current = invalidate;
    return () => { if (scopeRef.current === invalidate) scopeRef.current = null; };
  }, [scopeRef, invalidate]);
  const ids = useId();
  const [releases, setReleases] = useState<NarrativeRelease[]>([]);
  const releasesRef = useRef(releases); releasesRef.current = releases;
  const [refreshed, setRefreshed] = useState<ReadonlySet<string>>(() => new Set());
  const listLoaded = useRef(false);
  const [more, setMore] = useState(false), [listBusy, setListBusy] = useState(false);
  const [olderBusy, setOlderBusy] = useState(false), [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  const [item, setItem] = useState<NarrativeRelease | null>(null);
  const [itemBusy, setItemBusy] = useState(false), [itemError, setItemError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false), [acting, setActing] = useState<"cancel" | "retry" | null>(null);
  const [downloading, setDownloading] = useState<ArtifactKind[]>([]);
  const [notice, setNotice] = useState<string | null>(null), [actionError, setActionError] = useState<string | null>(null);
  const buildLock = useRef(false), actionLock = useRef(false), downloadLocks = useRef(new Set<ArtifactKind>());
  const urls = useRef(new Map<string, number>()), anchorHost = useRef<HTMLSpanElement>(null);
  const detail = useRef<HTMLElement>(null), statusMessage = useRef<HTMLParagraphElement>(null);
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  const revokeUrls = useCallback(() => {
    for (const [url, timer] of urls.current) { window.clearTimeout(timer); URL.revokeObjectURL(url); }
    urls.current.clear();
  }, []);
  useLayoutEffect(() => revokeUrls, [revokeUrls]);

  const loadItem = useCallback((id: string) => {
    setItemBusy(true);
    void run("item", signal => api.getNarrativeRelease(tenantId, projectId, id, signal), release => {
      if (selectedRef.current !== id) return;
      if (release.id !== id || !scopedRelease(release, tenantId, projectId)) { setItemError(mismatch); return; }
      setItem(current => current?.id === id ? newerRelease(current, release) : release);
      setReleases(rows => rows.map(row => row.id === id ? newerRelease(row, release) : row));
      setItemError(null);
    }, error => setItemError(releaseErrorMessage(error)), () => setItemBusy(false));
  }, [run, tenantId, projectId]);

  const select = useCallback((id: string) => {
    // Re-selecting keeps in-flight downloads and actions; another selection
    // synchronously invalidates every late item, action, history or Blob result.
    if (selectedRef.current === id) return;
    selectedRef.current = id; actionLock.current = false; downloadLocks.current.clear();
    for (const channel of ["item", "action", ...historyChannels, ...kinds.map(kind => `download:${kind}`)]) cancel(channel);
    revokeUrls(); setSelectedId(id); setItem(null); setItemError(null); setActing(null); setDownloading([]); setActionError(null);
    loadItem(id);
  }, [cancel, revokeUrls, loadItem]);

  const loadList = useCallback((older = false) => {
    const loaded = releasesRef.current;
    // A refresh re-reads every loaded row (up to the API cap) so statuses stay current.
    const limit = older ? PAGE : Math.min(100, Math.max(PAGE, loaded.length));
    if (older) setOlderBusy(true); else setListBusy(true);
    void run(older ? "older" : "list", signal => api.listNarrativeReleases(tenantId, projectId, {
      limit, beforeId: older ? loaded[loaded.length - 1]?.id : undefined, signal,
    }), rows => {
      if (!rows.every(row => scopedRelease(row, tenantId, projectId))) { setListError(mismatch); return; }
      setReleases(current => mergeReleases(current, rows, older));
      // Only the first and older pages decide whether more history exists.
      if (older || !listLoaded.current) { setMore(rows.length === PAGE); listLoaded.current = true; }
      if (!older) setRefreshed(new Set(rows.map(row => row.id)));
      setListError(null);
      if (!older && !selectedRef.current && rows[0]) select(rows[0].id);
    }, error => setListError(releaseErrorMessage(error)), () => { if (older) setOlderBusy(false); else setListBusy(false); });
  }, [run, tenantId, projectId, select]);

  useEffect(() => { loadList(); }, [loadList]);
  const selectedActive = item ? activeRelease(item.job) : false;
  useEffect(() => {
    if (!visible || !selectedId || itemBusy || !selectedActive) return;
    const timer = window.setTimeout(() => loadItem(selectedId), itemError ? 10000 : 2500);
    return () => window.clearTimeout(timer);
  }, [visible, selectedId, itemBusy, selectedActive, itemError, loadItem]);
  // Only rows the last refresh returned can be refreshed by polling the list.
  const listActive = releases.some(row => refreshed.has(row.id) && row.id !== selectedId && activeRelease(row.job));
  useEffect(() => {
    if (!visible || !listActive || listBusy) return;
    const timer = window.setTimeout(() => loadList(), listError ? 10000 : 5000);
    return () => window.clearTimeout(timer);
  }, [visible, listActive, listBusy, listError, loadList]);

  const targets = buildTargets(revision, history, headId);
  const target = targetId && targets.some(row => row.id === targetId) ? targetId : revision.id;
  const blocker = buildBlocker({ canWrite, dirty, saving, busy: building, targetId: target, releases });
  function build() {
    if (blocker || buildLock.current) return;
    buildLock.current = true; setBuilding(true); setActionError(null); setNotice(null);
    // Ambiguous failures keep this revision's key, so a resend cannot duplicate the release.
    const intent = prepareRelease(intents.builds.get(target) ?? null, target);
    intents.builds.set(target, intent);
    const before = selectedRef.current;
    void run("build", signal => api.createNarrativeRelease(tenantId, projectId, intent.revision_id, intent.idempotency_key, signal),
      release => {
        if (!scopedRelease(release, tenantId, projectId) || release.revision_id !== intent.revision_id) { setActionError(mismatch); return; }
        intents.builds.delete(intent.revision_id);
        const label = revisionLabel(release.revision_id, history, revision);
        const replay = replayedRelease(release, releasesRef.current.some(row => row.id === release.id));
        setReleases(current => mergeReleases(current, [release]));
        setNotice(replay ? `This build request for ${label} was already recorded. Showing its latest status.`
          : `Build requested for ${label}.`);
        // Never pull the user away from a release they chose while this request was pending.
        if (selectedRef.current === release.id) loadItem(release.id);
        else if (selectedRef.current === before) select(release.id);
      }, error => setActionError(releaseErrorMessage(error)), () => { buildLock.current = false; setBuilding(false); });
  }
  function retry() {
    const release = item;
    if (!release || !canWrite || actionLock.current || !["failed", "cancelled"].includes(release.job.status)) return;
    actionLock.current = true; setActing("retry"); setActionError(null); setNotice(null);
    const id = release.id, intent = prepareReleaseRetry(intents.retries.get(release.job.id) ?? null, release.job.id);
    intents.retries.set(intent.job_id, intent);
    void run("action", signal => api.retryNarrativeRelease(tenantId, projectId, id, intent.idempotency_key, signal), next => {
      if (selectedRef.current !== id) return;
      if (next.id !== id || !scopedRelease(next, tenantId, projectId)) { setActionError(mismatch); return; }
      intents.retries.delete(intent.job_id);
      setItem(current => current?.id === id ? newerRelease(current, next) : current);
      setReleases(rows => rows.map(row => row.id === id ? newerRelease(row, next) : row));
      setNotice("Retry requested. The same saved revision will be built again."); loadItem(id);
      // The Retry button disappears with the new attempt; keep focus on its status.
      window.requestAnimationFrame(() => statusMessage.current?.focus());
    }, error => setActionError(releaseErrorMessage(error)), () => { actionLock.current = false; setActing(null); });
  }
  function cancelBuild() {
    const release = item;
    if (!release || !canWrite || actionLock.current || !activeRelease(release.job) || release.job.cancel_requested) return;
    actionLock.current = true; setActing("cancel"); setActionError(null); setNotice(null);
    const id = release.id, jobId = release.job.id;
    void run("action", signal => api.cancelNarrativeRelease(tenantId, projectId, id, jobId, signal), job => {
      if (selectedRef.current !== id) return;
      if (job.id !== jobId) { setActionError(mismatch); return; }
      setItem(current => current?.id === id ? newerRelease(current, { ...current, job }) : current);
      setReleases(rows => rows.map(row => row.id === id ? newerRelease(row, { ...row, job }) : row));
      setNotice(job.status === "completed" ? "The build finished before it could be cancelled."
        : job.status === "cancelled" ? "Build cancelled." : "Cancellation requested.");
      loadItem(id);
    }, error => setActionError(releaseErrorMessage(error)), () => { actionLock.current = false; setActing(null); });
  }
  function download(release: NarrativeRelease, artifact: ReleaseArtifact) {
    const id = release.id, kind = artifact.kind;
    if (downloadLocks.current.has(kind)) return;
    downloadLocks.current.add(kind);
    setDownloading(rows => [...rows.filter(row => row !== kind), kind]); setActionError(null); setNotice(null);
    void run(`download:${kind}`, signal => api.downloadNarrativeArtifact(tenantId, projectId, id, artifact, signal), blob => {
      // The verified Blob may arrive late: re-check scope before any URL exists.
      const host = anchorHost.current;
      if (selectedRef.current !== id || !host) return;
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = artifact.filename; link.hidden = true;
      host.append(link); link.click(); link.remove();
      urls.current.set(url, window.setTimeout(() => { URL.revokeObjectURL(url); urls.current.delete(url); }, 60000));
      setNotice(`${artifactLabel(kind)} verified. Your browser is saving ${artifact.filename}.`);
    }, error => setActionError(releaseErrorMessage(error)), () => {
      downloadLocks.current.delete(kind); setDownloading(rows => rows.filter(row => row !== kind));
    });
  }
  async function saveDraft() {
    if (saving) return;
    setActionError(null); setNotice(null);
    const saved = await onSave();
    if (!saved) { setActionError("Your draft was not saved. Close Releases to review what needs attention."); return; }
    setTargetId(null); setNotice(`Saved revision ${saved.revision_number}. It is ready to build.`);
  }

  const artifacts = item ? readyArtifacts(item) : [];
  const selectedLabel = item ? revisionLabel(item.revision_id, history, revision) : "";
  const describedBy = dirty ? `${ids}-dirty` : blocker && !building ? `${ids}-blocker` : undefined;
  return <StudioDialog label="Releases" onClose={onClose}>
    <div className="studio-releases-body">
      <header className="studio-section-heading"><div><p className="studio-eyebrow">Releases</p>
        <h2 className="studio-releases-title">Build and download your game</h2>
        <p className="studio-hint">Each release turns one saved revision into an editable Godot project and a browser build. Builds keep running if you close this window.</p></div>
        <button type="button" className="studio-secondary" onClick={onClose}>Close releases</button></header>
      {canWrite ? <section className="studio-release-build" aria-label="New release">
        <label className="studio-field">Saved revision to build<select value={target} disabled={building || saving}
          onChange={event => setTargetId(event.target.value)}>
          {targets.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select>
          <small>Unsaved changes are never part of a release.</small></label>
        <CarriedLicenses tenantId={tenantId} projectId={projectId} revisionId={target} />
        {dirty && <div className="studio-notice studio-release-dirty"><span id={`${ids}-dirty`}>You have unsaved changes. Save them as a revision to build them.</span>
          <button type="button" className="studio-secondary" aria-disabled={saving} onClick={() => void saveDraft()}>{saving ? "Saving…" : "Save revision"}</button></div>}
        <div className="studio-actions"><button type="button" className="studio-primary" aria-disabled={Boolean(blocker)}
          aria-describedby={describedBy} onClick={build}>{building ? "Requesting build…" : "Build release"}</button>
          {blocker && !dirty && !building && <span className="studio-hint" id={`${ids}-blocker`}>{blocker}</span>}</div>
      </section> : <p className="studio-notice">Read-only access. You can follow builds and download ready releases.</p>}
      <div role="status">{notice && <p className="studio-notice">{notice}</p>}</div>
      {actionError && <p className="studio-error" role="alert">{actionError}</p>}
      <div className="studio-release-layout">
        <section className="studio-release-rail" aria-label="Release list">
          <div className="studio-section-heading"><h3>Release history</h3>
            <button type="button" className="studio-link" onClick={() => loadList()}>Refresh releases</button></div>
          {listError && <p className="studio-error" role="status">{listError}</p>}
          <ul className="studio-release-list">{releases.map(row => <li key={row.id}>
            <button type="button" className={`studio-release ${row.id === selectedId ? "selected" : ""}`}
              aria-pressed={row.id === selectedId} onClick={() => {
                select(row.id);
                // Single-column layouts show details below the list; bring them into view.
                if (window.matchMedia("(max-width: 820px)").matches) detail.current?.scrollIntoView({ block: "start" });
              }}>
              <span className={`studio-release-status is-${tone(row.job)}`}>{releaseStatus(row.job)}</span>
              <strong>{revisionLabel(row.revision_id, history, revision)}</strong>
              <small>Attempt {row.job.attempt_number} · {new Date(row.created_at).toLocaleString()}</small>
            </button></li>)}</ul>
          {!releases.length && <p className="studio-empty">{listBusy ? "Loading releases…"
            : "No releases yet. Build a saved revision to get a playable game and its Godot project."}</p>}
          {more && <button type="button" className="studio-secondary" aria-disabled={olderBusy}
            onClick={() => { if (!olderBusy) loadList(true); }}>{olderBusy ? "Loading older releases…" : "Load older releases"}</button>}
        </section>
        <section ref={detail} className="studio-release-detail" aria-label="Selected release">
          {!selectedId ? <p className="studio-hint">Choose a release to see its status and downloads.</p>
            : !item ? <>
              <p className={itemError ? "studio-error" : "studio-hint"} role="status">{itemError ?? "Loading release…"}</p>
              {itemError && <button type="button" className="studio-secondary" onClick={() => loadItem(selectedId)}>Try again</button>}
            </> : <>
            <div className="studio-section-heading"><h3>{selectedLabel}</h3>
              <span className={`studio-release-status is-${tone(item.job)}`}>{releaseStatus(item.job)}</span></div>
            <p ref={statusMessage} tabIndex={-1} className={item.job.status === "failed" ? "studio-error" : "studio-release-message"}
              role="status">{statusDetail(item)}</p>
            {itemError && <p className="studio-error" role="status">{itemError}</p>}
            {artifacts.length > 0 && <div className="studio-release-downloads" aria-label="Downloads">
              {artifacts.map(artifact => <button type="button" key={artifact.kind} className="studio-download"
                aria-disabled={downloading.includes(artifact.kind)} onClick={() => download(item, artifact)}>
                <strong>{artifactLabel(artifact.kind)}</strong>
                <small>{downloading.includes(artifact.kind) ? "Verifying download…" : `${formatBytes(artifact.size_bytes)} · ${artifact.kind === "manifest" ? "JSON" : "ZIP"}`}</small>
              </button>)}</div>}
            <div className="studio-actions">
              <button type="button" className="studio-secondary" onClick={() => onInspect(item.revision_id)}>View saved revision</button>
              {canWrite && activeRelease(item.job) && <button type="button" className="studio-secondary studio-danger"
                aria-disabled={item.job.cancel_requested || acting !== null} onClick={cancelBuild}>{acting === "cancel" ? "Cancelling…" : "Cancel build"}</button>}
              {canWrite && (item.job.status === "failed" || item.job.status === "cancelled") && <button type="button" className="studio-primary"
                aria-disabled={acting !== null} onClick={retry}>{acting === "retry" ? "Requesting retry…" : "Retry build"}</button>}
              <button type="button" className="studio-link" onClick={() => loadItem(item.id)}>Refresh status</button>
            </div>
            <dl className="studio-release-facts">
              <div><dt>Attempt</dt><dd>{item.job.attempt_number}</dd></div>
              <div><dt>Requested</dt><dd>{new Date(item.created_at).toLocaleString()}</dd></div>
              <div><dt>Engine</dt><dd>Godot {item.build_identity.godot_version} · runtime {item.build_identity.runtime_version}</dd></div>
              <div><dt>Package</dt><dd><code>{item.package_hash.slice(0, 16)}</code></dd></div>
            </dl>
            <ReleaseHistory key={`${item.id}:${item.job.id}`} tenantId={tenantId} projectId={projectId}
              releaseId={item.id} latestJob={item.job} run={run} />
          </>}
        </section>
      </div>
      <span ref={anchorHost} hidden />
    </div>
  </StudioDialog>;
}

/** The voice model licenses a build of this revision will carry, and the lines causing each (#178). */
function CarriedLicenses({ tenantId, projectId, revisionId }: { tenantId: string; projectId: string; revisionId: string }) {
  const [carried, setCarried] = useState<CarriedVoiceLicenses | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setCarried(null);
    api.getRevisionVoiceLicenses(tenantId, projectId, revisionId, controller.signal).then(setCarried, () => undefined);
    return () => controller.abort();
  }, [tenantId, projectId, revisionId]);
  const duties = carried?.licenses.filter(item => item.obligations !== "none") ?? [];
  if (!carried || !carried.licenses.length) return null;
  return <section className="studio-release-licenses" aria-label="Voice licenses in this release">
    <h3>Voice licenses this release carries</h3>
    {!duties.length && <p className="studio-hint">The voice clips in this revision put no duties on the game. NOTICES credits each model.</p>}
    <ul>{carried.licenses.map(item => <li key={item.id}>
      <strong>{item.name}</strong>{" "}
      <span className="studio-hint">{item.obligations === "player_terms" ? "NOTICES plus a one-time license screen for players"
        : item.obligations === "attribution" ? "NOTICES" : "no duties"}</span>
      {item.obligations !== "none" && <p className="studio-hint">{item.summary}</p>}
      {item.obligations !== "none" && item.lines.length > 0 && <p className="studio-hint">Caused by {item.lines.length === 1 ? "line" : "lines"}{" "}
        {item.lines.map(line => line.node_id).join(", ")}. Regenerate {item.lines.length === 1 ? "it" : "them"} with another voice model to drop this.</p>}
    </li>)}</ul>
    {carried.player_terms && <p className="studio-notice">Players will see a license screen once before they play, and can reread it from the menu.</p>}
  </section>;
}
