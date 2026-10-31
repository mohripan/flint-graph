import { useContext, useState } from "react";
import { CharacterProfilesContext, useNarrativeImage } from "./characterImages";
import { AssetThumb, IMAGE_KINDS, libraryAsset, useApprovedAssets } from "./libraryAssets";
import { POSITIONS, SLOT_CENTERS, applyStageNode, bindAsset, describeSnapshot, figureBox, resolvedTheme, sceneStage, setSceneStage } from "./stageModel";
import type { StageEdit, StageSnapshot } from "./stageModel";
import type { StagePosition, StoryDraft } from "./types";

const message = (error: unknown) => error instanceof Error ? error.message : "Could not change the stage.";

/** Story format 1 cannot hold a stage; this offers the explicit upgrade instead. */
export function UpgradeNotice({ onUpgrade, readOnly }: { onUpgrade: () => void; readOnly: boolean }) {
  return <div className="studio-upgrade" role="note">
    <strong>Stage and theme need the newer story format.</strong>
    <p>Upgrading saves a new revision that can show backgrounds, characters on stage and a styled text box. Your earlier revisions stay as they are.</p>
    {!readOnly && <button type="button" className="studio-secondary" onClick={onUpgrade}>Use stage &amp; theme</button>}
  </div>;
}

// The stage step that opens a scene: background plus who enters, moves or leaves.
// What earlier scenes left on stage is shown above it, so creators only state changes.
export function SceneStage({ story, head, inherited, readOnly, onChange, onError }: {
  story: StoryDraft; head: string; inherited: StageSnapshot | undefined; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
}) {
  const context = useContext(CharacterProfilesContext);
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const { assets, failed } = useApprovedAssets(tenantId, projectId);
  const [picking, setPicking] = useState<"background" | "cg" | null>(null);
  const edit = sceneStage(story, head);
  const cast = Object.entries(story.characters).filter(([, character]) => Object.keys(character.sprites ?? {}).length);
  const apply = (next: StageEdit, base: StoryDraft = story) => {
    try { onChange(setSceneStage(base, head, next), `${head}:stage`); } catch (error) { onError(message(error)); }
  };
  const backgrounds = (assets ?? []).filter(asset => IMAGE_KINDS.has(asset.kind) && asset.media_type === "image/png");
  const current = typeof edit.background === "string" ? story.assets[edit.background] : undefined;
  const cg = typeof edit.cg === "string" ? story.assets[edit.cg] : undefined;
  const snapshot = applyStageNode(inherited ?? { background: null, cg: null, characters: {} }, story.nodes[head]);
  const leaving = Object.keys(inherited?.characters ?? {});
  const free = POSITIONS.find(position => !edit.show.some(entry => entry.position === position));
  const addable = cast.find(([id]) => !edit.show.some(entry => entry.character === id));

  return <section className="studio-stage" aria-label="Stage at the start of this scene">
    <div className="studio-stage-head"><h3>Stage</h3>
      <p className="studio-hint">From earlier scenes: {describeSnapshot(story, inherited).join(" · ")}</p></div>
    <SceneStagePreview story={story} snapshot={snapshot} tenantId={tenantId} projectId={projectId} />
    <fieldset className="studio-stage-fields" disabled={readOnly}>
      <div className="studio-stage-background">
        <span className="studio-stage-label">Background</span>
        <AssetThumb tenantId={tenantId} projectId={projectId} asset={libraryAsset(assets, current?.sha256)}
          label={edit.background === undefined ? "Unchanged" : edit.background === null ? "None" : edit.background} />
        <div className="studio-actions">
          <button type="button" className="studio-secondary" onClick={() => setPicking(value => value === "background" ? null : "background")}>
            {picking === "background" ? "Done" : "Choose…"}</button>
          {edit.background !== undefined && <button type="button" className="studio-link" onClick={() => {
            const { background: _, ...rest } = edit; apply(rest);
          }}>Keep earlier</button>}
          {edit.background !== null && <button type="button" className="studio-link" onClick={() => apply({ ...edit, background: null })}>No background</button>}
        </div>
      </div>
      <div className="studio-stage-background">
        <span className="studio-stage-label">Event CG</span>
        <AssetThumb tenantId={tenantId} projectId={projectId} asset={libraryAsset(assets, cg?.sha256)}
          label={edit.cg === undefined ? "Unchanged" : edit.cg === null ? "None" : edit.cg} />
        <div className="studio-actions">
          <button type="button" className="studio-secondary" onClick={() => setPicking(value => value === "cg" ? null : "cg")}>
            {picking === "cg" ? "Done" : "Choose CG…"}</button>
          {edit.cg !== undefined && <button type="button" className="studio-link" onClick={() => {
            const { cg: _, ...rest } = edit; apply(rest);
          }}>Keep earlier CG</button>}
          {edit.cg !== null && <button type="button" className="studio-link" onClick={() => apply({ ...edit, cg: null })}>Clear CG</button>}
        </div>
        <p className="studio-hint">Covers the stage while dialogue continues. Clearing it reveals the background and characters.</p>
      </div>
      {picking && <div className="studio-stage-picker" role="listbox" aria-label={picking === "cg" ? "CG images" : "Backgrounds"}>
        {Object.entries(story.assets).filter(([, asset]) => asset.kind === "image").map(([id, asset]) =>
          <button type="button" role="option" key={`story:${id}`} aria-selected={(picking === "cg" ? edit.cg : edit.background) === id}
            className="studio-stage-option" onClick={() => { apply({ ...edit, [picking]: id }); setPicking(null); }}>
            <AssetThumb tenantId={tenantId} projectId={projectId} asset={libraryAsset(assets, asset.sha256)} label={id} /><small>{id}</small>
          </button>)}
        {failed && <p className="studio-error">The asset library could not be loaded.</p>}
        {assets && !backgrounds.length && <p className="studio-hint">Approve or upload backgrounds in Assets first.</p>}
        {(picking === "cg" ? (assets ?? []).filter(asset => asset.media_type === "image/png") : backgrounds).map(asset =>
          <button type="button" role="option" key={asset.id} aria-selected={(picking === "cg" ? cg : current)?.sha256 === asset.sha256}
          className="studio-stage-option" onClick={() => {
            try {
              const bound = bindAsset(story, asset);
              apply({ ...edit, [picking]: bound.key }, bound.story); setPicking(null);
            } catch (error) { onError(message(error)); }
          }}><AssetThumb tenantId={tenantId} projectId={projectId} asset={asset} label={asset.name} /><small>{asset.name}</small></button>)}
      </div>}
      <div className="studio-stage-cast">
        <span className="studio-stage-label">Characters</span>
        {!cast.length && <p className="studio-hint">Give characters expression sprites in Characters to place them on stage.</p>}
        {edit.show.map((entry, index) => {
          const sprites = Object.keys(story.characters[entry.character]?.sprites ?? {});
          const change = (patch: Partial<typeof entry>) => {
            const show = edit.show.map((item, at) => at === index ? { ...item, ...patch } : item);
            apply({ ...edit, show });
          };
          const resetPlace = () => {
            const show = edit.show.map((item, at) => {
              if (at !== index) return item;
              const { x: _, ...rest } = item; return rest;
            });
            apply({ ...edit, show });
          };
          return <div className="studio-stage-row" key={`${entry.character}:${index}`}>
            <select aria-label="Character" value={entry.character} onChange={event => {
              const sprite = Object.keys(story.characters[event.target.value]?.sprites ?? {})[0];
              change({ character: event.target.value, sprite });
            }}>{cast.map(([id, character]) => <option key={id} value={id}>{character.name}</option>)}</select>
            <select aria-label="Expression" value={entry.sprite} onChange={event => change({ sprite: event.target.value })}>
              {sprites.map(sprite => <option key={sprite} value={sprite}>{sprite}</option>)}</select>
            <select aria-label="Position" value={entry.position} onChange={event => change({ position: event.target.value as StagePosition })}>
              {POSITIONS.map(position => <option key={position} value={position}>{position}</option>)}</select>
            <label className="studio-stage-place">
              <span>Place {entry.x ?? SLOT_CENTERS[entry.position]}%</span>
              <input type="range" min={0} max={100} aria-label="Horizontal place"
                value={entry.x ?? SLOT_CENTERS[entry.position]} onChange={event => change({ x: Number(event.target.value) })} />
            </label>
            {entry.x !== undefined && <button type="button" className="studio-link" onClick={resetPlace}>Slot default</button>}
            <button type="button" className="studio-link studio-danger"
              onClick={() => apply({ ...edit, show: edit.show.filter((_, at) => at !== index) })}>Remove</button>
          </div>;
        })}
        {addable && free && edit.show.length < 3 && <button type="button" className="studio-link" onClick={() => {
          const [id, character] = addable;
          apply({ ...edit, hide: edit.hide.filter(item => item !== id),
            show: [...edit.show, { character: id, sprite: Object.keys(character.sprites ?? {})[0], position: free }] });
        }}>Place a character</button>}
      </div>
      {leaving.length > 0 && <div className="studio-stage-leaving">
        <span className="studio-stage-label">Leaves at this point</span>
        {leaving.map(id => <label key={id} className="studio-check">
          <input type="checkbox" checked={edit.hide.includes(id)} disabled={edit.show.some(entry => entry.character === id)}
            onChange={event => apply({ ...edit, hide: event.target.checked ? [...edit.hide, id] : edit.hide.filter(item => item !== id) })} />
          <span>{story.characters[id]?.name ?? id}</span></label>)}
      </div>}
    </fieldset>
  </section>;
}

/** A scene's actual stage, including inherited CGs and changes underneath the overlay. */
function SceneStagePreview({ story, snapshot, tenantId, projectId }: {
  story: StoryDraft; snapshot: StageSnapshot; tenantId: string; projectId: string;
}) {
  const { assets } = useApprovedAssets(tenantId, projectId);
  const imageId = (key: string | null) => libraryAsset(assets, key ? story.assets[key]?.sha256 : undefined)?.id ?? null;
  const background = useNarrativeImage(tenantId, projectId, imageId(snapshot.background), "image");
  const cg = useNarrativeImage(tenantId, projectId, imageId(snapshot.cg), "image");
  const theme = resolvedTheme(story);
  return <div className="studio-scene-stage-preview" aria-label="Scene stage preview" role="img">
    {background && <img className="studio-scene-cover" src={background} alt="" />}
    {Object.entries(snapshot.characters).map(([id, placed]) => placed !== "?" &&
      <SceneFigure key={id} story={story} id={id} placed={placed} tenantId={tenantId} projectId={projectId} />)}
    {cg && <img className="studio-scene-cover studio-scene-cg" src={cg} alt={`CG ${snapshot.cg}`} />}
    {snapshot.cg === "?" && <span className="studio-scene-cg-label">CG varies by path</span>}
    {snapshot.cg && snapshot.cg !== "?" && !cg && <span className="studio-scene-cg-label">CG: {snapshot.cg}</span>}
    <div className="studio-scene-dialogue" style={{ background: theme.textbox.background, color: theme.textbox.text,
      borderColor: theme.textbox.border, width: `${theme.textbox.width}%`,
      top: theme.textbox.position === "top" ? "8%" : theme.textbox.position === "middle" ? "42%" : undefined,
      bottom: theme.textbox.position === "bottom" ? "4%" : undefined }}>Dialogue continues over the stage.</div>
  </div>;
}

function SceneFigure({ story, id, placed, tenantId, projectId }: {
  story: StoryDraft; id: string; placed: Exclude<StageSnapshot["characters"][string], "?">; tenantId: string; projectId: string;
}) {
  const { assets } = useApprovedAssets(tenantId, projectId);
  const character = story.characters[id];
  const key = character?.sprites?.[placed.sprite];
  const asset = libraryAsset(assets, key ? story.assets[key]?.sha256 : undefined);
  const url = useNarrativeImage(tenantId, projectId, asset?.id ?? null, "image");
  const box = asset?.width && asset.height ? figureBox(asset.width, asset.height, character?.stage, placed.x ?? SLOT_CENTERS[placed.position]) : null;
  return url && box ? <img className="studio-scene-figure" src={url} alt="" style={{ left: `${box.left}%`, top: `${box.top}%`,
    width: `${box.width}%`, height: `${box.height}%` }} /> : null;
}
