import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { api } from "../lib/api";
import type { ImageJob, NarrativeImage } from "../lib/api";
import { useNarrativeImage } from "./characterImages";
import { isActive, jobStatus } from "./characterModel";
import {
  EXPRESSION_PRESETS, MAX_EXPRESSIONS, faceBoxFromAlpha, faceView, moveBox, normalizeExpression, resizeBox, validExpression,
} from "./expressionModel";
import type { Box } from "./expressionModel";
import { libraryAsset, refreshLibrary, useApprovedAssets } from "./libraryAssets";
import { bindAsset, setSprite } from "./stageModel";
import type { StoryDraft } from "./types";
import "./expressions.css";

const message = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback;

// New expressions for a character, repainted from one of its sprites so the body,
// outfit and hair stay identical (ADR 0041). Results are candidates; "Use as"
// approves one and sets it as that expression in the draft.
export function ExpressionStudio({ id, story, tenantId, projectId, readOnly, onChange, onError }: {
  id: string; story: StoryDraft; tenantId: string; projectId: string; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
}) {
  const { assets } = useApprovedAssets(tenantId, projectId);
  const latest = useRef(story); latest.current = story;
  const bases = Object.entries(story.characters[id]?.sprites ?? {}).flatMap(([expression, key]) => {
    const asset = libraryAsset(assets, story.assets[key]?.sha256);
    return asset && asset.media_type === "image/png" && asset.width && asset.height ? [{ expression, asset }] : [];
  });
  const [open, setOpen] = useState(false);
  const [baseExpression, setBaseExpression] = useState<string | null>(null);
  const base = bases.find(item => item.expression === baseExpression) ?? bases[0];
  const [chosen, setChosen] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [box, setBox] = useState<Box | null>(null);
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = jobs.find(isActive) ?? null;

  useEffect(() => {
    const controller = new AbortController();
    api.listExpressionJobs(tenantId, projectId, id, controller.signal).then(listed => setJobs(listed.jobs))
      .catch(() => { if (!controller.signal.aborted) setNotice("Earlier expressions could not be loaded."); });
    return () => controller.abort();
  }, [tenantId, projectId, id]);
  const activeId = active?.id;
  useEffect(() => {
    if (!activeId) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      api.getImageJob(tenantId, projectId, activeId, controller.signal)
        .then(job => setJobs(current => current.map(item => item.id === job.id ? job : item))).catch(() => undefined);
    }, 1500);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [activeId, tenantId, projectId]);

  const add = (name: string) => {
    const value = normalizeExpression(name);
    if (!validExpression(value) || chosen.includes(value) || chosen.length >= MAX_EXPRESSIONS) return;
    setChosen(current => [...current, value]);
  };
  async function generate() {
    if (!base || !box || !chosen.length || busy || active) return;
    setBusy(true); setNotice(null);
    try {
      const job = await api.createExpressionJob(tenantId, projectId, id, {
        base_asset_id: base.asset.id, face_box: box, expressions: chosen, idempotency_key: crypto.randomUUID(),
      });
      setJobs(current => [job, ...current]); setChosen([]);
    } catch (error) { setNotice(message(error, "Could not start the expressions.")); }
    finally { setBusy(false); }
  }
  async function use(asset: NarrativeImage, expression: string) {
    try {
      const approved = asset.status === "candidate" ? await api.approveNarrativeAsset(tenantId, projectId, asset.id) : asset;
      refreshLibrary();
      setJobs(current => current.map(job => ({ ...job, assets: job.assets.map(item => item.id === approved.id ? approved : item) })));
      const bound = bindAsset(latest.current, approved);
      onChange(setSprite(bound.story, id, expression, bound.key));
      setNotice(`“${expression}” now uses this image.`);
    } catch (error) { onError(message(error, "Could not use this image.")); }
  }
  async function discard(asset: NarrativeImage) {
    try {
      await api.discardNarrativeImage(tenantId, projectId, asset.id);
      setJobs(current => current.map(job => ({ ...job, assets: job.assets.filter(item => item.id !== asset.id) })));
    } catch (error) { setNotice(message(error, "Could not discard this image.")); }
  }

  const results = jobs.flatMap(job => job.assets.map(asset => ({ asset, expression: String(asset.provenance.expression ?? "") })))
    .filter(item => item.expression);
  if (!bases.length) {
    return <p className="studio-hint">Add an expression with an approved image first; new expressions are repainted from it.</p>;
  }
  return <div className="expression-studio">
    {!open ? <button type="button" className="studio-secondary" disabled={readOnly} onClick={() => setOpen(true)}>
      Generate expressions…</button>
      : <div className="expression-panel">
        <div className="studio-section-heading"><strong>New expressions from one sprite</strong>
          <button type="button" className="studio-link" onClick={() => setOpen(false)}>Close</button></div>
        <p className="studio-hint">Only the face inside the box is repainted; hair, outfit and size stay the same. Drag the box onto the face, or use the arrow keys (Shift resizes).</p>
        {bases.length > 1 && <label className="expression-base">Start from
          <select value={base?.expression} onChange={event => { setBaseExpression(event.target.value); setBox(null); }}>
            {bases.map(item => <option key={item.expression} value={item.expression}>{item.expression}</option>)}</select></label>}
        {base && <FaceBoxEditor tenantId={tenantId} projectId={projectId} asset={base.asset} box={box} onBox={setBox} />}
        <div className="expression-chips" role="group" aria-label="Expressions to generate">
          {EXPRESSION_PRESETS.map(name => <button type="button" key={name} aria-pressed={chosen.includes(name)}
            disabled={!chosen.includes(name) && chosen.length >= MAX_EXPRESSIONS}
            onClick={() => chosen.includes(name) ? setChosen(chosen.filter(item => item !== name)) : add(name)}>{name}</button>)}
          {chosen.filter(name => !EXPRESSION_PRESETS.includes(name)).map(name => <button type="button" key={name} aria-pressed
            onClick={() => setChosen(chosen.filter(item => item !== name))}>{name} ×</button>)}
        </div>
        <div className="expression-custom">
          <input value={custom} maxLength={40} placeholder="Or type one, for example: teasing" aria-label="Custom expression"
            onChange={event => setCustom(event.target.value)}
            onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); add(custom); setCustom(""); } }} />
          <button type="button" className="studio-link" disabled={!validExpression(custom) || chosen.length >= MAX_EXPRESSIONS}
            onClick={() => { add(custom); setCustom(""); }}>Add</button>
        </div>
        <div className="studio-actions">
          <button type="button" className="studio-primary" disabled={readOnly || busy || Boolean(active) || !chosen.length || !box}
            onClick={() => void generate()}>{active ? "Generating…" : chosen.length
              ? `Generate ${chosen.length} expression${chosen.length === 1 ? "" : "s"}` : "Generate expressions"}</button>
          <span className="studio-hint">Up to {MAX_EXPRESSIONS} at a time · about 10 seconds each on this computer's GPU.</span>
        </div>
      </div>}
    {active && <div className="studio-job" role="status">
      <div className="studio-job-bar"><span style={{ width: `${Math.max(4, (active.progress / active.count) * 100)}%` }} /></div>
      <span>{jobStatus(active).replace("portraits", "expressions").replace("portrait", "expression")}</span></div>}
    {jobs[0] && !isActive(jobs[0]) && jobs[0].status !== "completed" && <p className="studio-notice">{jobStatus(jobs[0])}</p>}
    {notice && <p className="studio-hint" role="status">{notice}</p>}
    {results.length > 0 && <div className="expression-results">
      {results.map(({ asset, expression }) => <ExpressionResult key={asset.id} tenantId={tenantId} projectId={projectId}
        asset={asset} expression={expression} readOnly={readOnly}
        inUse={story.characters[id]?.sprites?.[expression] !== undefined
          && story.assets[story.characters[id]!.sprites![expression]]?.sha256 === asset.sha256}
        onUse={() => void use(asset, expression)} onDiscard={() => void discard(asset)} />)}
    </div>}
  </div>;
}

function FaceBoxEditor({ tenantId, projectId, asset, box, onBox }: {
  tenantId: string; projectId: string; asset: NarrativeImage; box: Box | null; onBox: (box: Box) => void;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset.id, "image");
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: "move" | "resize"; x: number; y: number; start: Box } | null>(null);
  const width = asset.width ?? 1, height = asset.height ?? 1;
  // The first guess comes from the image's own transparency.
  useEffect(() => {
    if (!url || box) return;
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.drawImage(image, 0, 0);
      const pixels = context.getImageData(0, 0, width, height).data;
      const alpha = new Uint8Array(width * height);
      for (let index = 0; index < alpha.length; index += 1) alpha[index] = pixels[index * 4 + 3];
      onBox(faceBoxFromAlpha(alpha, width, height));
    };
    image.src = url;
  }, [url, box, width, height, onBox]);
  const scale = () => width / (frame.current?.clientWidth || width);
  const start = (mode: "move" | "resize") => (event: PointerEvent<HTMLElement>) => {
    if (!box) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { mode, x: event.clientX, y: event.clientY, start: box };
  };
  const move = (event: PointerEvent<HTMLElement>) => {
    const state = drag.current;
    if (!state) return;
    const dx = (event.clientX - state.x) * scale(), dy = (event.clientY - state.y) * scale();
    onBox(state.mode === "move" ? moveBox(state.start, dx, dy, width, height) : resizeBox(state.start, dx, dy, width, height));
  };
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!box) return;
    const step = 2 * Math.max(1, Math.round(scale()));
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
    if (!delta) return;
    event.preventDefault();
    onBox(event.shiftKey ? resizeBox(box, delta[0] + delta[1], delta[0] + delta[1], width, height)
      : moveBox(box, delta[0], delta[1], width, height));
  };
  const percent = (value: number, total: number) => `${(value / total) * 100}%`;
  return <div className="expression-frame" ref={frame} style={{ aspectRatio: `${width} / ${height}` }}>
    {url ? <img src={url} alt="" draggable={false} /> : <span className="studio-hint">Loading…</span>}
    {box && <div className="expression-box" role="slider" tabIndex={0} aria-label="Face box"
      aria-valuetext={`${box[0]}, ${box[1]}, ${box[2] - box[0]} pixels wide`}
      style={{ left: percent(box[0], width), top: percent(box[1], height),
        width: percent(box[2] - box[0], width), height: percent(box[3] - box[1], height) }}
      onPointerDown={start("move")} onPointerMove={move} onPointerUp={() => { drag.current = null; }} onKeyDown={keys}>
      <span className="expression-handle" onPointerDown={start("resize")} onPointerMove={move}
        onPointerUp={() => { drag.current = null; }} /></div>}
  </div>;
}

function ExpressionResult({ tenantId, projectId, asset, expression, readOnly, inUse, onUse, onDiscard }: {
  tenantId: string; projectId: string; asset: NarrativeImage; expression: string; readOnly: boolean;
  inUse: boolean; onUse: () => void; onDiscard: () => void;
}) {
  // The face is a small part of a full-body sprite, so the preview zooms onto it.
  const box = asset.provenance.face_box as Box | undefined;
  const view = box && asset.width && asset.height ? faceView(box, asset.width, asset.height) : null;
  const url = useNarrativeImage(tenantId, projectId, asset.id, view ? "image" : "thumbnail");
  return <figure className="expression-result">
    <span className={view ? "expression-thumb face" : "expression-thumb"}>{!url ? "…" : view
      ? <img src={url} alt="" style={{ width: `${view.width}%`, left: `${view.left}%`, top: `${view.top}%` }} />
      : <img src={url} alt="" />}</span>
    <figcaption><strong>{expression}</strong>
      {inUse ? <small>In use</small> : !readOnly && <button type="button" className="studio-secondary" onClick={onUse}>Use as “{expression}”</button>}
      {!inUse && !readOnly && <button type="button" className="studio-link studio-danger" onClick={onDiscard}>Discard</button>}
    </figcaption>
  </figure>;
}
