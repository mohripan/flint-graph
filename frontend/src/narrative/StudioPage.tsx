import { useCallback, useContext, useDeferredValue, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, api } from "../lib/api";
import { useWorkspace } from "../lib/workspace";
import { draftReducer, initialDraftState, prepareSave } from "./draftState";
import type { SavedConflict, SourceDiagnostic } from "./draftState";
import { Field } from "./FormFields";
import { DraftHistory } from "./history";
import { addScene } from "./model";
import { buildPassages } from "./passages";
import { PassageEditor } from "./PassageEditor";
import { SceneHierarchy } from "./SceneHierarchy";
import { SceneOptionsContext } from "./sceneOptions";
import { CharacterProfilesProvider } from "./characterImages";
import { AssetLibrary } from "./AssetLibrary";
import { CharacterStudio } from "./CharacterStudio";
import { LookPanel } from "./LookPanel";
import { stageBefore } from "./stageModel";
import { StatePanel, StoryPanel } from "./RecordPanels";
import { RouteMap } from "./RouteMap";
import { SceneForm } from "./SceneForm";
import { StudioDialog } from "./StudioDialog";
import { PreviewDialog } from "./PreviewDialog";
import { ReleasesDialog } from "./ReleasesDialog";
import { AssistantPage } from "./AssistantPage";
import { releaseIntents } from "./releaseModel";
import { StudioNavSlot, StudioSideNav } from "./StudioNav";
import { PANELS as panels, currentSection } from "./studioSections";
import type { Panel } from "./studioSections";
import type { NarrativeProject, NarrativeRevision, RevisionSummary, RevisionWrite, StoryDraft, StoryNode } from "./types";
import "./studio.css";

function readSelection(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function writeSelection(key: string, id: string | null): void {
  try { if (id) localStorage.setItem(key, id); else localStorage.removeItem(key); } catch { /* IDs are optional convenience. */ }
}
/** Keeps ?project= (and ?thread= while that project's conversation is open) in the link. */
function linkProject(projectId: string | null, keepThread: boolean): void {
  try {
    const url = new URL(location.href);
    if (projectId) url.searchParams.set("project", projectId); else url.searchParams.delete("project");
    if (!projectId || !keepThread) url.searchParams.delete("thread");
    history.replaceState(history.state, "", url);
  } catch { /* The link is a convenience. */ }
}
function parsedStory(source: string): StoryDraft | null {
  try {
    const value = JSON.parse(source) as StoryDraft;
    return value && (value.schema_version === "1" || value.schema_version === "2") && value.nodes && value.characters && value.variables && value.assets
      ? value : null;
  } catch { return null; }
}
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export function StudioPage({ onDirtyChange }: {
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { workspace } = useWorkspace();
  if (!workspace) throw new Error("A workspace is required.");
  const tenantId = workspace.id, storageKey = `flintgraph.studio.project.${tenantId}`;
  const canWrite = workspace.role !== "viewer";
  const navSlot = useContext(StudioNavSlot);
  const [state, dispatch] = useReducer(draftReducer, undefined, () => initialDraftState());
  const stateRef = useRef(state); stateRef.current = state;
  const [projects, setProjects] = useState<NarrativeProject[]>([]);
  const [listBusy, setListBusy] = useState(false);
  const [listMore, setListMore] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [historyRows, setHistoryRows] = useState<RevisionSummary[]>([]);
  const [historyMore, setHistoryMore] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [peek, setPeek] = useState<NarrativeRevision | null>(null);
  const peekEpoch = useRef(0);
  const closePeek = useCallback(() => { peekEpoch.current += 1; setPeek(null); }, []);
  const [preview, setPreview] = useState<NarrativeRevision | null>(null);
  const previewOpener = useRef<HTMLButtonElement | null>(null);
  const closePreview = useCallback(() => {
    setPreview(null);
    window.requestAnimationFrame(() => previewOpener.current?.focus());
  }, []);
  const onPreview = (revision: NarrativeRevision, opener: HTMLButtonElement) => {
    previewOpener.current = opener; setPreview(revision);
  };
  const [releasesOpen, setReleasesOpen] = useState(false);
  const releasesOpener = useRef<HTMLButtonElement | null>(null);
  // The open dialog registers its request scope; closing paths invalidate it
  // synchronously, before React commits the unmount.
  const releaseScope = useRef<(() => void) | null>(null);
  const releaseIntentStore = useRef(releaseIntents());
  // The assistant page is remounted per project; its scope is invalidated synchronously
  // on every path that changes project, collection or access.
  const assistantScope = useRef<(() => void) | null>(null), hierarchyScope = useRef<(() => void) | null>(null);
  const viewKey = `flintgraph.studio.view.${tenantId}`;
  // A link with ?project=…&thread=… opens that project's conversation (shared or reported by ID).
  const linked = useRef(new URLSearchParams(location.search));
  const [view, setView] = useState<"editor" | "assistant">(() =>
    linked.current.get("thread") || readSelection(viewKey) === "assistant" ? "assistant" : "editor");
  const chooseView = (next: "editor" | "assistant") => {
    setView(next); writeSelection(viewKey, next === "assistant" ? next : null);
    if (next === "editor" && stateRef.current.project) linkProject(stateRef.current.project.id, false);
  };
  const endReleases = useCallback(() => {
    releaseScope.current?.(); assistantScope.current?.(); hierarchyScope.current?.(); setReleasesOpen(false);
  }, []);
  const closeReleases = useCallback(() => {
    setReleasesOpen(false);
    window.requestAnimationFrame(() => releasesOpener.current?.focus());
  }, []);
  const [panel, setPanel] = useState<Panel>("write");
  const [sceneId, setSceneId] = useState("");
  const [nodeEditor, setNodeEditor] = useState<string | null>(null);
  const [rawMode, setRawMode] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [, redrawHistory] = useState(0);
  const epoch = useRef(0), listEpoch = useRef(0), historyEpoch = useRef(0), mounted = useRef(true);
  const controllers = useRef(new Set<AbortController>());
  const history = useRef(new DraftHistory());
  const pendingSave = useRef<RevisionWrite | null>(null), saving = useRef(false);
  const pendingCreate = useRef<{ name: string; key: string } | null>(null), creating = useRef(false);
  const dirty = Boolean(state.revision && (state.source !== state.revision.story_json || state.notices !== state.revision.notices));
  const dirtyRef = useRef(dirty); dirtyRef.current = dirty;
  // Form edits already hold the edited object; reuse it instead of re-parsing megabytes.
  const lastEdit = useRef<{ source: string; story: StoryDraft } | null>(null);
  const story = useMemo(() => rawMode ? null
    : lastEdit.current?.source === state.source ? lastEdit.current.story : parsedStory(state.source), [state.source, rawMode]);
  const scenes = useMemo(() => story ? buildPassages(story) : null, [story]);
  // What is on stage as each scene begins (story format 2); deferred so typing stays fast.
  const settledStory = useDeferredValue(story);
  const stageMap = useMemo(() => settledStory?.schema_version === "2" ? stageBefore(settledStory) : null, [settledStory]);
  const optionsKey = scenes ? scenes.passages.map(item => `${item.id}\u0001${item.title.slice(0, 48)}`).join("\u0000") : "";
  const sceneOptions = useMemo(() => {
    if (!optionsKey) return null;
    const rows = optionsKey.split("\u0000").map(row => row.split("\u0001"));
    return { ids: new Set(rows.map(([id]) => id)),
      options: rows.map(([id, title]) => <option key={id} value={id}>{id} · {title}</option>) };
  }, [optionsKey]);
  const passage = scenes?.passages.find(item => item.id === (scenes.owner.get(sceneId) ?? sceneId));

  function controller(): AbortController {
    const value = new AbortController(); controllers.current.add(value); return value;
  }
  function abortAll() { for (const value of controllers.current) value.abort(); controllers.current.clear(); }
  const loseAccess = useCallback((message: string) => {
    endReleases(); releaseIntentStore.current = releaseIntents();
    epoch.current += 1; listEpoch.current += 1; historyEpoch.current += 1;
    abortAll(); pendingSave.current = null; saving.current = false;
    pendingCreate.current = null; creating.current = false; setCreateBusy(false); setCreateName("");
    setListBusy(false); setHistoryBusy(false); setListMore(false); setHistoryMore(false);
    history.current.clear(); setPeek(null); setPreview(null); setHistoryRows([]); setProjects([]); setRawMode(false);
    writeSelection(storageKey, null);
    dispatch({ type: "clear", generation: epoch.current, message });
  }, [storageKey, endReleases]);
  const releaseAccessLost = useCallback(() => loseAccess("Your workspace access changed. Reload your workspaces before continuing."), [loseAccess]);
  const failure = useCallback((error: unknown, generation: number) => {
    if (!mounted.current || epoch.current !== generation || (error instanceof Error && error.name === "AbortError")) return;
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      loseAccess("Your workspace access changed. Reload your workspaces before continuing."); return;
    }
    let conflict: SavedConflict | undefined;
    const errors = error instanceof ApiError ? error.problem?.errors ?? [] : [];
    const first = errors[0];
    if (error instanceof ApiError && error.status === 409 && error.problem?.type === "urn:flint-graph:error:stale-revision"
      && typeof first?.conflict_revision_id === "string" && typeof first.observed_head_revision_id === "string") {
      conflict = { revisionId: first.conflict_revision_id, headId: first.observed_head_revision_id };
    }
    const diagnostics: SourceDiagnostic[] = errors.slice(0, 100).flatMap(item =>
      typeof item.code === "string" && typeof item.location === "string"
        ? [{ code: item.code.slice(0, 120), location: item.location.slice(0, 200) }] : []);
    dispatch({ type: "failed", generation, message: errorMessage(error), conflict, diagnostics });
  }, [loseAccess]);

  const refreshProjects = useCallback(async (older = false) => {
    const request = controller(), version = ++listEpoch.current, generation = epoch.current;
    setListBusy(true);
    try {
      const rows = await api.listNarrativeProjects(tenantId, { limit: 25,
        beforeId: older ? projects[projects.length - 1]?.id : undefined, signal: request.signal });
      if (!mounted.current || version !== listEpoch.current || epoch.current !== generation) return;
      setProjects(previous => older ? [...previous, ...rows.filter(row => !previous.some(item => item.id === row.id))] : rows);
      setListMore(rows.length === 25);
    } catch (error) { failure(error, generation); }
    finally { controllers.current.delete(request); if (mounted.current && version === listEpoch.current) setListBusy(false); }
  }, [tenantId, projects, failure]);

  const refreshHistory = useCallback(async (projectId: string, generation: number, older?: string) => {
    const request = controller(), version = ++historyEpoch.current; setHistoryBusy(true);
    try {
      const rows = await api.listNarrativeRevisions(tenantId, projectId, { limit: 25, beforeId: older, signal: request.signal });
      if (!mounted.current || epoch.current !== generation || version !== historyEpoch.current) return;
      setHistoryRows(previous => older ? [...previous, ...rows.filter(row => !previous.some(item => item.id === row.id))] : rows);
      setHistoryMore(rows.length === 25);
    } catch (error) { failure(error, generation); }
    finally { controllers.current.delete(request); if (mounted.current && epoch.current === generation && version === historyEpoch.current) setHistoryBusy(false); }
  }, [tenantId, failure]);

  const loadProject = useCallback(async (id: string) => {
    abortAll(); const generation = ++epoch.current, request = controller();
    pendingSave.current = null; saving.current = false; history.current.clear();
    setPeek(null); setPreview(null); endReleases(); setHistoryRows([]); setNotice(null); setRawMode(false); setPanel("write");
    dispatch({ type: "load", generation });
    try {
      const project = await api.getNarrativeProject(tenantId, id, request.signal);
      if (!mounted.current || epoch.current !== generation) return;
      const revision = await api.getNarrativeRevision(tenantId, id, project.head_revision_id, request.signal);
      if (!mounted.current || epoch.current !== generation) return;
      dispatch({ type: "loaded", generation, project, revision });
      setSceneId(parsedStory(revision.story_json)?.entry ?? "");
      writeSelection(storageKey, id); void refreshHistory(id, generation);
      linkProject(id, new URLSearchParams(location.search).get("project") === id);
    } catch (error) {
      if (mounted.current && epoch.current === generation && error instanceof ApiError && error.status === 404) writeSelection(storageKey, null);
      failure(error, generation);
    } finally { controllers.current.delete(request); }
  }, [tenantId, storageKey, refreshHistory, failure, endReleases]);

  useEffect(() => {
    mounted.current = true;
    const selected = linked.current.get("project") ?? readSelection(storageKey);
    if (selected) void loadProject(selected);
    void refreshProjects();
    return () => { mounted.current = false; epoch.current += 1; listEpoch.current += 1;
      abortAll(); history.current.clear(); pendingSave.current = null; onDirtyChange(false); };
    // Project rows must not retrigger source loading or erase a working draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => { if (dirtyRef.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);
  }, []);

  function snapshot(): string { return JSON.stringify({ source: stateRef.current.source, notices: stateRef.current.notices, rawMode }); }
  function edit(source: string, notices: string, group?: string) {
    const current = stateRef.current;
    if (!canWrite || current.saving || saving.current || !current.revision) return;
    if (source === current.source && notices === current.notices) return;
    history.current.record(snapshot, group); redrawHistory(value => value + 1);
    dispatch({ type: "edit", source, notices }); setNotice(null);
  }
  function updateStory(next: StoryDraft, group?: string) {
    const source = JSON.stringify(next);
    lastEdit.current = { source, story: next };
    edit(source, stateRef.current.notices, group);
  }
  function restoreHistory(direction: "undo" | "redo") {
    if (!canWrite || saving.current) return;
    const stored = history.current[direction](snapshot()); redrawHistory(value => value + 1);
    if (!stored) return;
    const restored = JSON.parse(stored) as { source: string; notices: string; rawMode: boolean };
    dispatch({ type: "edit", source: restored.source, notices: restored.notices }); setRawMode(restored.rawMode);
    if (restored.rawMode) setPanel("source");
  }
  async function save(): Promise<NarrativeRevision | null> {
    const current = stateRef.current;
    if (!canWrite || saving.current || !current.revision || !current.project) return null;
    saving.current = true; const generation = epoch.current, request = controller();
    const payload = prepareSave(pendingSave.current, current.revision.id, current.source, current.notices);
    pendingSave.current = payload; history.current.breakGroup(); setNotice(null);
    dispatch({ type: "saving", generation, request: payload });
    try {
      const revision = await api.saveNarrativeRevision(tenantId, current.project.id, payload, request.signal);
      if (!mounted.current || epoch.current !== generation) return null;
      dispatch({ type: "saved", generation, revision }); pendingSave.current = null;
      setProjects(rows => rows.map(row => row.id === current.project!.id ? { ...row, head_revision_id: revision.id } : row));
      setNotice(`Saved revision ${revision.revision_number}.`); void refreshHistory(current.project.id, generation);
      return revision;
    } catch (error) { failure(error, generation); return null; }
    finally { controllers.current.delete(request); if (epoch.current === generation) saving.current = false; }
  }
  function acceptedRevision(revision: NarrativeRevision) {
    const current = stateRef.current;
    if (!current.project || revision.project_id !== current.project.id || dirtyRef.current) return;
    const generation = epoch.current;
    history.current.breakGroup();
    dispatch({ type: "saved", generation, revision });
    setProjects(rows => rows.map(row => row.id === current.project!.id ? { ...row, head_revision_id: revision.id } : row));
    const accepted = parsedStory(revision.story_json);
    if (accepted && !Object.prototype.hasOwnProperty.call(accepted.nodes, sceneId)) setSceneId(accepted.entry);
    setNotice(`Accepted the assistant's proposal as revision ${revision.revision_number}.`);
    void refreshHistory(current.project.id, generation);
  }
  async function upgradeStory() {
    const current = stateRef.current;
    if (!canWrite || saving.current || !current.project || !current.revision) return;
    if (dirtyRef.current) { setNotice("Save or undo your changes before upgrading the story format."); return; }
    saving.current = true; const generation = epoch.current, request = controller();
    try {
      const revision = await api.upgradeNarrativeProject(tenantId, current.project.id, current.revision.id,
        crypto.randomUUID(), request.signal);
      if (!mounted.current || epoch.current !== generation) return;
      history.current.clear(); redrawHistory(value => value + 1);
      dispatch({ type: "saved", generation, revision });
      setProjects(rows => rows.map(row => row.id === current.project!.id ? { ...row, head_revision_id: revision.id } : row));
      setNotice(`This story now uses stage and theme (revision ${revision.revision_number}).`);
      void refreshHistory(current.project.id, generation);
    } catch (error) { failure(error, generation); }
    finally { controllers.current.delete(request); if (epoch.current === generation) saving.current = false; }
  }
  function assistantConflict() {
    const current = stateRef.current.project;
    if (current) void refreshHistory(current.id, epoch.current);
  }
  const saveRef = useRef(save); saveRef.current = save;
  const undoRef = useRef(restoreHistory); undoRef.current = restoreHistory;
  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if (document.querySelector("dialog[open]")) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "s") { event.preventDefault(); if (dirtyRef.current) void saveRef.current(); }
      if (event.key.toLowerCase() === "z") { event.preventDefault(); undoRef.current(event.shiftKey ? "redo" : "undo"); }
    };
    window.addEventListener("keydown", keys); return () => window.removeEventListener("keydown", keys);
  }, []);

  async function createProject(event: React.FormEvent) {
    event.preventDefault(); const name = createName.trim();
    if (!canWrite || !name || creating.current) return;
    creating.current = true; setCreateBusy(true); const request = controller(), generation = epoch.current;
    const identity = pendingCreate.current?.name === name ? pendingCreate.current : { name, key: crypto.randomUUID() };
    pendingCreate.current = identity;
    try {
      const project = await api.createNarrativeProject(tenantId, name, identity.key, request.signal);
      if (!mounted.current || epoch.current !== generation) return;
      listEpoch.current += 1; setListBusy(false); setProjects(rows => [project, ...rows.filter(row => row.id !== project.id)]);
      pendingCreate.current = null; creating.current = false; setCreateBusy(false); setCreateName("");
      if (epoch.current === generation) await loadProject(project.id);
    } catch (error) { failure(error, generation); }
    finally { controllers.current.delete(request); if (mounted.current && epoch.current === generation) { creating.current = false; setCreateBusy(false); } }
  }
  function confirmLeave(): boolean { return !dirtyRef.current || window.confirm("Leave this draft without saving? Your last saved revision will remain available."); }
  function chooseProject(id: string) { if (confirmLeave()) void loadProject(id); }
  function collection() {
    if (!confirmLeave()) return;
    abortAll(); epoch.current += 1; pendingSave.current = null; saving.current = false;
    history.current.clear(); setPeek(null); setPreview(null); endReleases(); setHistoryRows([]); setRawMode(false); writeSelection(storageKey, null);
    linkProject(null, false);
    dispatch({ type: "clear", generation: epoch.current }); void refreshProjects();
  }
  function choosePanel(next: Panel) {
    if (rawMode && dirtyRef.current && next !== "source" && next !== "history") {
      setNotice("Save valid source before returning to forms. Your raw draft is still here."); return;
    }
    setPanel(next); if (next === "source") setRawMode(true); else if (next !== "history") setRawMode(false);
  }
  function locateDiagnostic(location: string) {
    const [section, id] = location.split(".");
    if (section === "nodes" && id && story && Object.prototype.hasOwnProperty.call(story.nodes, id)) {
      setSceneId(id); choosePanel("write");
    } else if (section === "variables") choosePanel("state");
    else if (section === "characters") choosePanel("characters");
    else if (section === "theme") choosePanel("look");
    else if (["title", "language", "entry", "NOTICES"].includes(section)) choosePanel("story");
    else choosePanel("source");
  }
  async function inspectRevision(id: string) {
    const current = stateRef.current.project; if (!current) return;
    const generation = epoch.current, version = ++peekEpoch.current, request = controller();
    try {
      const revision = await api.getNarrativeRevision(tenantId, current.id, id, request.signal);
      if (mounted.current && epoch.current === generation && version === peekEpoch.current) setPeek(revision);
    } catch (error) { failure(error, generation); }
    finally { controllers.current.delete(request); }
  }
  async function useRevisionAsDraft() {
    const selected = peek, current = stateRef.current.project;
    if (!selected || !current || !canWrite || !confirmLeave()) return;
    const before = stateRef.current;
    const generation = epoch.current, request = controller();
    try {
      const project = await api.getNarrativeProject(tenantId, current.id, request.signal);
      const head = await api.getNarrativeRevision(tenantId, project.id, project.head_revision_id, request.signal);
      if (!mounted.current || epoch.current !== generation) return;
      const now = stateRef.current;
      if (saving.current || now.revision?.id !== before.revision?.id || now.source !== before.source || now.notices !== before.notices) {
        setNotice("Your draft changed while the current head was loading. Review it before copying this revision again."); return;
      }
      pendingSave.current = null; history.current.clear(); setRawMode(false); setPanel("write"); setPeek(null);
      dispatch({ type: "loaded", generation, project, revision: head });
      dispatch({ type: "edit", source: selected.story_json, notices: selected.notices });
      setSceneId(parsedStory(selected.story_json)?.entry ?? "");
      setNotice(`Revision ${selected.revision_number} copied into a draft against the current head. Save to keep it.`);
    } catch (error) { failure(error, generation); }
    finally { controllers.current.delete(request); }
  }
  function add(kind: StoryNode["type"]) {
    if (!story || !canWrite) return;
    try { const added = addScene(story, kind); updateStory(added.story); setSceneId(added.id); setPanel("write"); }
    catch (error) { setNotice(errorMessage(error)); }
  }
  const readOnly = !canWrite || state.saving;
  const common = story ? { story, readOnly, onChange: updateStory, onError: setNotice } : null;
  const hierarchy = scenes && state.project ? <SceneHierarchy key={`${tenantId}:${state.project.id}`} tenantId={tenantId}
    projectId={state.project.id} passages={scenes.passages} owner={scenes.owner} from={scenes.from} selected={sceneId}
    canWrite={canWrite} scopeRef={hierarchyScope} onAccessLost={releaseAccessLost}
    onSelect={id => { setSceneId(id); setNodeEditor(null); choosePanel("write"); }} /> : null;

  const assistantView = view === "assistant" && Boolean(state.project && state.revision);

  return <SceneOptionsContext.Provider value={sceneOptions}>
  <CharacterProfilesProvider tenantId={tenantId} projectId={state.project?.id ?? ""}>
  <div className={`narrative-studio ${assistantView ? "is-assistant" : ""} ${navSlot ? "has-side-nav" : ""}`} role="region" aria-label="Narrative studio" onBlurCapture={() => history.current.breakGroup()}>
    {releasesOpen && state.project && state.revision && <ReleasesDialog key={`${tenantId}:${state.project.id}`}
      tenantId={tenantId} projectId={state.project.id} headId={state.project.head_revision_id} revision={state.revision}
      history={historyRows} canWrite={canWrite} dirty={dirty} saving={state.saving} onSave={save}
      intents={releaseIntentStore.current} scopeRef={releaseScope}
      onInspect={id => void inspectRevision(id)} onClose={closeReleases} onAccessLost={releaseAccessLost} />}
    {preview && <PreviewDialog key={preview.id} revision={preview} onClose={closePreview} />}
    {navSlot && state.project && createPortal(<StudioSideNav projectName={state.project.name}
      current={currentSection(assistantView, panel)} assistantReady={Boolean(state.revision)} onProjects={collection}
      onAssistant={() => chooseView("assistant")} onPanel={next => { chooseView("editor"); choosePanel(next); }} />, navSlot)}
    <header className="studio-heading"><div><p className="studio-eyebrow">Narrative studio</p>
      <h1>{state.project?.name ?? "Your stories"}</h1>
      <p>{state.project ? `Revision ${state.revision?.revision_number ?? "…"} · ${state.saving ? "Saving…" : state.conflict ? "Conflict copy saved" : dirty ? "Unsaved changes" : "Saved"}` : "Write a branching story. Shape its choices. Play what you authored."}</p></div>
      {state.project && <div className="studio-actions">
        <button type="button" className="studio-secondary studio-projects-button" onClick={collection}>Projects</button>
        <div className="studio-view-switch" role="group" aria-label="Studio view">
          <button type="button" aria-pressed={!assistantView} onClick={() => chooseView("editor")}>Editor</button>
          <button type="button" aria-pressed={assistantView} disabled={!state.revision} onClick={() => chooseView("assistant")}>Assistant</button></div>
        {!assistantView && <><button type="button" className="studio-secondary" disabled={!canWrite || !history.current.canUndo || state.saving} onClick={() => restoreHistory("undo")}>Undo</button>
        <button type="button" className="studio-secondary" disabled={!canWrite || !history.current.canRedo || state.saving} onClick={() => restoreHistory("redo")}>Redo</button></>}
        {onPreview && <button type="button" className="studio-secondary" disabled={!state.revision || state.saving}
          onClick={async event => { const opener = event.currentTarget;
            const revision = dirty && canWrite ? await save() : state.revision; if (revision) onPreview(revision, opener); }}>
          {dirty && canWrite ? "Save & playtest" : "Playtest"}</button>}
        <button type="button" className="studio-secondary" disabled={!state.revision}
          onClick={event => { releasesOpener.current = event.currentTarget; setReleasesOpen(true); }}>Releases</button>
        {canWrite && <button type="button" className="studio-primary" disabled={!dirty || state.saving}
          onClick={() => void save()}>{state.saving ? "Saving…" : state.request && state.error && !state.conflict ? "Retry save" : "Save revision"}</button>}
      </div>}
    </header>
    {!canWrite && <p className="studio-notice">Read-only workspace access. You can inspect saved stories and revisions.</p>}
    {(notice || state.error) && <div role="status" className={state.error ? "studio-error" : "studio-notice"}>
      {notice ?? state.error}
      {state.diagnostics.map((item, index) => <p key={index}><button type="button" className="studio-link"
        onClick={() => locateDiagnostic(item.location)}><code>{item.location}</code></button> · {item.code.replaceAll("_", " ")}</p>)}
    </div>}
    {state.conflict && <section className="studio-conflict" aria-label="Saved conflict">
      <strong>Your writing was retained as a conflict revision.</strong>
      <p>The current story was preserved. Inspect both versions before choosing what to keep.</p>
      <div className="studio-actions"><button type="button" className="studio-secondary"
        onClick={() => void inspectRevision(state.conflict!.revisionId)}>View saved copy</button>
        <button type="button" className="studio-secondary" onClick={() => void inspectRevision(state.conflict!.headId)}>Review other revision</button></div>
    </section>}
    {state.loading ? <p role="status" className="studio-empty">Opening the saved story…</p> : !state.project ? <>
      {canWrite && <form className="studio-create" onSubmit={event => void createProject(event)}>
        <Field label="New project name"><input value={createName} maxLength={200}
          onChange={event => setCreateName(event.target.value)} placeholder="A title for your next story" /></Field>
        <button type="submit" className="studio-primary" disabled={!createName.trim() || createBusy}>{createBusy ? "Creating…" : "Create story"}</button>
      </form>}
      <div className="studio-section-heading"><h2>Projects</h2><button type="button" className="studio-link" disabled={listBusy}
        onClick={() => void refreshProjects()}>Refresh projects</button></div>
      <div className="studio-projects">{projects.map(project => <button type="button" className="studio-project" key={project.id}
        disabled={createBusy} onClick={() => chooseProject(project.id)}><span>Authored story</span><h3>{project.name}</h3>
        <p>Open the writing desk <span aria-hidden="true">↗</span></p></button>)}</div>
      {!projects.length && <p className="studio-empty">{listBusy ? "Loading projects…" : "Your first story starts here. A blank project needs no documents or AI service."}</p>}
      {listMore && <button type="button" className="studio-secondary" disabled={listBusy} onClick={() => void refreshProjects(true)}>Load older projects</button>}
    </> : assistantView && state.revision ? <AssistantPage key={`${tenantId}:${state.project.id}`}
      tenantId={tenantId} projectId={state.project.id} revision={state.revision} focus={sceneId || null}
      canWrite={canWrite} dirty={dirty} saving={state.saving} scopeRef={assistantScope} onSave={save}
      onAccepted={acceptedRevision} onConflict={assistantConflict} onInspect={id => void inspectRevision(id)}
      onOpenEditor={() => chooseView("editor")} onAccessLost={releaseAccessLost} />
    : <div className="studio-workspace">
      <div className="studio-editor">
      <nav className="studio-tabs" aria-label="Story editor panels">{panels.map(([id, label]) => <button type="button" key={id}
        aria-pressed={panel === id} className={`${panel === id ? "selected" : ""} studio-tab-${id} ${id === "write" && panel === "scenes" ? "wide-selected" : ""}`} onClick={() => choosePanel(id)}>{label}</button>)}</nav>
      <div className={`studio-desk ${panel === "scenes" ? "show-scenes" : ""} ${panel === "characters" || panel === "assets" || panel === "look" ? "no-rail" : ""}`}>
        <aside className="studio-rail" aria-label="Scenes">{hierarchy ?? <p className="studio-hint">Open Write to see scenes.</p>}</aside>
        <section className="studio-sheet">
          {panel === "source" ? <fieldset className="studio-form" disabled={readOnly}>
            <h2>Advanced source</h2><p className="studio-hint">Raw source is kept exactly as you type it. Strict validation runs when saving; invalid or duplicate fields are not silently repaired.</p>
            <Field label="Story JSON"><textarea className="studio-source" rows={22} spellCheck={false} value={state.source}
              onChange={event => edit(event.target.value, state.notices, "raw-source")} /></Field>
          </fieldset> : panel === "history" ? <div className="studio-form"><h2>Saved revisions</h2>
            <button type="button" className="studio-link" disabled={historyBusy} onClick={() => void refreshHistory(state.project!.id, epoch.current)}>Refresh revisions</button>
            {historyRows.map(row => <button type="button" className="studio-revision" key={row.id} onClick={() => void inspectRevision(row.id)}>
              <strong>Revision {row.revision_number}</strong><span>{row.conflicted ? "Conflict copy" : row.id === state.project?.head_revision_id ? "Current" : "Saved"}</span>
              <small>{new Date(row.created_at).toLocaleString()}</small></button>)}
            {historyMore && <button type="button" className="studio-secondary" disabled={historyBusy}
              onClick={() => void refreshHistory(state.project!.id, epoch.current, historyRows[historyRows.length - 1]?.id)}>Load older revisions</button>}
          </div> : common ? panel === "map" ? <RouteMap story={common.story} selected={sceneId} onSelect={id => { setSceneId(id); setPanel("write"); }} />
            : panel === "characters" ? <CharacterStudio {...common} onUpgrade={canWrite ? () => void upgradeStory() : undefined} />
            : panel === "assets" && state.project ? <AssetLibrary tenantId={tenantId} projectId={state.project.id} canWrite={canWrite}
              characterNames={Object.fromEntries(Object.entries(common.story.characters).map(([id, character]) => [id, character.name]))} />
            : panel === "look" ? <LookPanel {...common} onUpgrade={() => void upgradeStory()} />
            : panel === "state" ? <StatePanel {...common} />
            : panel === "story" ? <><StoryPanel {...common} /><Field label="Content notices"><textarea rows={5} value={state.notices} disabled={readOnly}
                onChange={event => edit(state.source, event.target.value, "notices")} /></Field></>
            : nodeEditor && common.story.nodes[nodeEditor] ? <><button type="button" className="studio-link"
                onClick={() => setNodeEditor(null)}>← Back to the scene script</button>
                <SceneForm {...common} sceneId={nodeEditor} /></>
            : passage ? <PassageEditor key={passage.id} {...common} passage={passage} onOpenNode={setNodeEditor}
                inherited={stageMap?.get(passage.id)} onUpgrade={canWrite ? () => void upgradeStory() : undefined}
                onDeleted={next => { updateStory(next); setSceneId(next.entry); }} />
            : <SceneForm {...common} sceneId={sceneId} />
            : <p className="studio-empty">Open Source to inspect this draft, or reopen a valid saved revision.</p>}
        </section>
      </div>
      {canWrite && story && <footer className="studio-add"><span>Add to the story</span><div className="studio-actions">
        {(["line", "choice", "end", "set", "branch"] as const).map(type => <button type="button" className="studio-secondary" key={type}
          disabled={readOnly || ((type === "set" || type === "branch") && !Object.keys(story.variables).length)} onClick={() => add(type)}>
          {type === "line" ? "Add scene" : type === "choice" ? "Add choice" : type === "end" ? "Add ending" : type === "set" ? "Add state change" : "Add condition"}</button>)}
      </div><small>Save explicitly. Ctrl/⌘ + S saves a revision.</small></footer>}
      </div>
    </div>}
    {peek && <StudioDialog label={`Revision ${peek.revision_number}`} onClose={closePeek}>
      <div className="studio-peek-body"><div className="studio-section-heading"><h2>Revision {peek.revision_number}{peek.conflicted ? " · conflict copy" : ""}</h2>
        <button type="button" className="studio-secondary" onClick={closePeek}>Close revision</button></div>
        <p>This saved snapshot will not change the working draft until you choose to copy it.</p>
        <Field label="Saved story source"><textarea className="studio-source" readOnly rows={14} value={peek.story_json} /></Field>
        {canWrite && <button type="button" className="studio-primary" onClick={() => void useRevisionAsDraft()}>Copy into a new draft against current head</button>}
        {onPreview && <button type="button" className="studio-secondary" onClick={event => onPreview(peek, event.currentTarget)}>Playtest this revision</button>}
      </div>
    </StudioDialog>}
  </div>
  </CharacterProfilesProvider>
  </SceneOptionsContext.Provider>;
}
