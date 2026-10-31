import { useState } from "react";
import type { NarrativeImage } from "../lib/api";
import { useNarrativeImage } from "./characterImages";
import { AssetThumb, SPRITE_KINDS, firstBackground, libraryAsset, useApprovedAssets } from "./libraryAssets";
import { UpgradeNotice } from "./StageEditor";
import {
  DEFAULT_SCALE, bindAsset, expressionId, figureBox, removeSprite, setCharacterColor, setCharacterFraming, setSprite,
  spriteUses,
} from "./stageModel";
import type { CharacterFraming, StoryDraft } from "./types";

const message = (error: unknown) => error instanceof Error ? error.message : "Could not change this character.";

// How a character appears on stage: a name colour and one sprite per expression,
// chosen from approved library sprites, images or portraits.
export function CharacterSprites({ id, story, tenantId, projectId, readOnly, onChange, onError, onUpgrade }: {
  id: string; story: StoryDraft; tenantId: string; projectId: string; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void; onUpgrade?: () => void;
}) {
  const { assets, failed } = useApprovedAssets(tenantId, projectId);
  const [picking, setPicking] = useState<{ expression: string | null } | null>(null);
  const [name, setName] = useState("");
  const character = story.characters[id];
  if (story.schema_version !== "2") {
    return onUpgrade ? <section className="studio-character-stage"><h3>On stage</h3>
      <UpgradeNotice readOnly={readOnly} onUpgrade={onUpgrade} /></section> : null;
  }
  const sprites = Object.entries(character.sprites ?? {});
  const choices = (assets ?? []).filter(asset => SPRITE_KINDS.has(asset.kind) && asset.media_type === "image/png");
  const run = (action: () => StoryDraft, group?: string) => {
    try { onChange(action(), group); } catch (error) { onError(message(error)); }
  };
  function pick(assetIndex: number) {
    const asset = choices[assetIndex];
    run(() => {
      const bound = bindAsset(story, asset);
      const expression = picking?.expression ?? expressionId(bound.story, id, name || asset.name);
      return setSprite(bound.story, id, expression, bound.key);
    });
    setPicking(null); setName("");
  }
  return <section className="studio-character-stage" aria-label="On stage">
    <h3>On stage</h3>
    <fieldset className="studio-form" disabled={readOnly}>
      <div className="studio-look-color">
        <span className="studio-stage-label">Name colour</span>
        <input type="color" aria-label="Name colour" value={character.color ?? "#d5ae68"}
          onChange={event => run(() => setCharacterColor(story, id, event.target.value), `character:${id}:color`)} />
        <code>{character.color ?? "theme"}</code>
        {character.color && <button type="button" className="studio-link" onClick={() => run(() => setCharacterColor(story, id, null))}>Use the theme</button>}
      </div>
      <Framing id={id} story={story} tenantId={tenantId} projectId={projectId} assets={assets}
        onChange={(framing, group) => run(() => setCharacterFraming(story, id, framing), group)} />
      <p className="studio-hint">Expressions are the sprites this character shows on stage. Lines can switch between them.</p>
      {!sprites.length && <p className="studio-empty">No expressions yet. Add one to place this character on stage.</p>}
      <ul className="studio-sprite-list">
        {sprites.map(([expression, key]) => {
          const uses = spriteUses(story, id, expression);
          return <li key={expression}>
            <AssetThumb tenantId={tenantId} projectId={projectId} asset={libraryAsset(assets, story.assets[key]?.sha256)} label={key} />
            <span><strong>{expression}</strong><small>{uses ? `Used ${uses === 1 ? "once" : `${uses} times`}` : "Not used yet"}</small></span>
            {!readOnly && <span className="studio-actions">
              <button type="button" className="studio-link" onClick={() => setPicking({ expression })}>Change image</button>
              <button type="button" className="studio-link studio-danger" onClick={() => run(() => removeSprite(story, id, expression))}>Remove</button>
            </span>}
          </li>;
        })}
      </ul>
      {!readOnly && !picking && <div className="studio-sprite-add">
        <input value={name} maxLength={64} placeholder="Expression, for example happy" aria-label="New expression name"
          onChange={event => setName(event.target.value)} />
        <button type="button" className="studio-secondary" disabled={sprites.length >= 32}
          onClick={() => setPicking({ expression: null })}>Add expression…</button>
      </div>}
      {picking && <div className="studio-stage-picker" role="listbox" aria-label="Sprite images">
        <div className="studio-section-heading"><span className="studio-stage-label">
          {picking.expression ? `Image for “${picking.expression}”` : `Image for “${name || "new expression"}”`}</span>
          <button type="button" className="studio-link" onClick={() => setPicking(null)}>Cancel</button></div>
        {failed && <p className="studio-error">The asset library could not be loaded.</p>}
        {assets && !choices.length && <p className="studio-hint">Approve transparent sprites from this character's generated images, or upload sprites in Assets.</p>}
        {choices.map((asset, index) => <button type="button" role="option" aria-selected={false} key={asset.id}
          className="studio-stage-option sprite" onClick={() => pick(index)}>
          <AssetThumb tenantId={tenantId} projectId={projectId} asset={asset} label={asset.name} /><small>{asset.name}</small></button>)}
      </div>}
    </fieldset>
  </section>;
}

// How large the character appears on stage and where their head sits. Full-body sprites
// drawn taller than the screen are cut off below it, as visual novels usually show them.
function Framing({ id, story, tenantId, projectId, assets, onChange }: {
  id: string; story: StoryDraft; tenantId: string; projectId: string; assets: NarrativeImage[] | null;
  onChange: (framing: CharacterFraming | null, group?: string) => void;
}) {
  const character = story.characters[id];
  const framing = character.stage;
  const scale = framing?.scale ?? DEFAULT_SCALE;
  const top = framing?.top ?? Math.max(0, 100 - scale);
  const spriteKey = Object.values(character.sprites ?? {})[0];
  const sprite = libraryAsset(assets, spriteKey ? story.assets[spriteKey]?.sha256 : undefined);
  const spriteUrl = useNarrativeImage(tenantId, projectId, sprite?.id ?? null, "image");
  const backdrop = useNarrativeImage(tenantId, projectId, libraryAsset(assets, firstBackground(story))?.id ?? null, "image");
  const box = sprite?.width && sprite.height ? figureBox(sprite.width, sprite.height, framing, 50) : null;
  return <div className="studio-framing">
    <div className="studio-framing-controls">
      <span className="studio-stage-label">Size on stage</span>
      <label className="studio-stage-place"><span>Height {framing ? `${scale}%` : "fits the slot"}</span>
        <input type="range" min={40} max={300} value={scale} aria-label="Size on stage"
          onChange={event => onChange({ ...framing, scale: Number(event.target.value) }, `character:${id}:framing`)} /></label>
      <label className="studio-stage-place"><span>Top edge {top}%</span>
        <input type="range" min={-50} max={100} value={top} aria-label="Top edge"
          onChange={event => onChange({ ...framing, scale, top: Number(event.target.value) }, `character:${id}:framing`)} /></label>
      <p className="studio-hint">Above 100% the figure continues below the screen, for example from the thighs up at about 160%.</p>
      {framing && <button type="button" className="studio-link" onClick={() => onChange(null)}>Fit to the slot</button>}
    </div>
    <div className="studio-framing-preview" role="img" aria-label="Preview of the character on stage"
      style={backdrop ? { backgroundImage: `url(${backdrop})` } : undefined}>
      {spriteUrl && box ? <img src={spriteUrl} alt="" style={{ left: `${box.left}%`, top: `${box.top}%`,
        width: `${box.width}%`, height: `${box.height}%` }} />
        : <span>Add an expression to preview the framing.</span>}
    </div>
  </div>;
}
