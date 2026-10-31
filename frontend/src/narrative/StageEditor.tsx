import { useContext, useState } from "react";
import { CharacterProfilesContext } from "./characterImages";
import { AssetThumb, IMAGE_KINDS, libraryAsset, useApprovedAssets } from "./libraryAssets";
import { POSITIONS, SLOT_CENTERS, bindAsset, describeSnapshot, sceneStage, setSceneStage } from "./stageModel";
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
  const [picking, setPicking] = useState(false);
  const edit = sceneStage(story, head);
  const cast = Object.entries(story.characters).filter(([, character]) => Object.keys(character.sprites ?? {}).length);
  const apply = (next: StageEdit, base: StoryDraft = story) => {
    try { onChange(setSceneStage(base, head, next), `${head}:stage`); } catch (error) { onError(message(error)); }
  };
  const backgrounds = (assets ?? []).filter(asset => IMAGE_KINDS.has(asset.kind) && asset.media_type === "image/png");
  const current = typeof edit.background === "string" ? story.assets[edit.background] : undefined;
  const leaving = Object.keys(inherited?.characters ?? {});
  const free = POSITIONS.find(position => !edit.show.some(entry => entry.position === position));
  const addable = cast.find(([id]) => !edit.show.some(entry => entry.character === id));

  return <section className="studio-stage" aria-label="Stage at the start of this scene">
    <div className="studio-stage-head"><h3>Stage</h3>
      <p className="studio-hint">From earlier scenes: {describeSnapshot(story, inherited).join(" · ")}</p></div>
    <fieldset className="studio-stage-fields" disabled={readOnly}>
      <div className="studio-stage-background">
        <span className="studio-stage-label">Background</span>
        <AssetThumb tenantId={tenantId} projectId={projectId} asset={libraryAsset(assets, current?.sha256)}
          label={edit.background === undefined ? "Unchanged" : edit.background === null ? "None" : edit.background} />
        <div className="studio-actions">
          <button type="button" className="studio-secondary" onClick={() => setPicking(value => !value)}>
            {picking ? "Done" : "Choose…"}</button>
          {edit.background !== undefined && <button type="button" className="studio-link" onClick={() => {
            const { background: _, ...rest } = edit; apply(rest);
          }}>Keep earlier</button>}
          {edit.background !== null && <button type="button" className="studio-link" onClick={() => apply({ ...edit, background: null })}>No background</button>}
        </div>
      </div>
      {picking && <div className="studio-stage-picker" role="listbox" aria-label="Backgrounds">
        {failed && <p className="studio-error">The asset library could not be loaded.</p>}
        {assets && !backgrounds.length && <p className="studio-hint">Approve or upload backgrounds in Assets first.</p>}
        {backgrounds.map(asset => <button type="button" role="option" key={asset.id} aria-selected={current?.sha256 === asset.sha256}
          className="studio-stage-option" onClick={() => {
            try {
              const bound = bindAsset(story, asset);
              apply({ ...edit, background: bound.key }, bound.story); setPicking(false);
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
