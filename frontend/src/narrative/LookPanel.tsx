import { useContext, useState } from "react";
import type { CSSProperties } from "react";
import { CharacterProfilesContext, useNarrativeImage } from "./characterImages";
import { Field } from "./FormFields";
import { firstBackground, libraryAsset, useApprovedAssets, useAssetFont } from "./libraryAssets";
import { UpgradeNotice } from "./StageEditor";
import { SLOT_CENTERS, bindAsset, figureBox, inkOn, joinColor, resetTheme, resolvedTheme, setThemeValue, splitColor } from "./stageModel";
import type { ResolvedTheme } from "./stageModel";
import type { StoryDraft } from "./types";

type Part = keyof ResolvedTheme;
const message = (error: unknown) => error instanceof Error ? error.message : "Could not change the look.";

// The game's look: text box, name box, choices and font, with a live preview drawn
// to scale with the same rules as the Godot stage view.
export function LookPanel({ story, readOnly, onChange, onError, onUpgrade }: {
  story: StoryDraft; readOnly: boolean; onChange: (story: StoryDraft, group?: string) => void;
  onError: (message: string) => void; onUpgrade: () => void;
}) {
  const context = useContext(CharacterProfilesContext);
  const tenantId = context?.tenantId ?? "", projectId = context?.projectId ?? "";
  const { assets } = useApprovedAssets(tenantId, projectId);
  const [screen, setScreen] = useState<"line" | "choice">("line");
  const v2 = story.schema_version === "2";
  const theme = resolvedTheme(story);
  const set = <P extends Part>(part: P, field: keyof ResolvedTheme[P], value: string | number | boolean | null) => {
    try { onChange(setThemeValue(story, part, field, value), `theme:${part}.${String(field)}`); }
    catch (error) { onError(message(error)); }
  };
  const fonts = (assets ?? []).filter(asset => asset.media_type !== "image/png");
  const fontKey = theme.font.asset;
  const fontAsset = libraryAsset(assets, fontKey ? story.assets[fontKey]?.sha256 : undefined);
  const family = useAssetFont(tenantId, projectId, fontAsset?.id ?? null);
  const color = (part: Part, field: string, label: string, alpha = false) => {
    const value = (theme[part] as Record<string, string>)[field];
    const { rgb, alpha: opacity } = splitColor(value);
    return <Field label={label}><span className="studio-look-color">
      <input type="color" value={rgb} aria-label={`${label} colour`}
        onChange={event => set(part, field as never, joinColor(event.target.value, alpha ? opacity : 255))} />
      {alpha && <input type="range" min={0} max={100} value={Math.round(opacity / 2.55)} aria-label={`${label} opacity`}
        onChange={event => set(part, field as never, joinColor(rgb, Number(event.target.value) * 2.55))} />}
      <code>{value}</code></span></Field>;
  };

  return <section className="studio-look" aria-label="Look">
    <div className="studio-section-heading"><h2>Look</h2>
      {v2 && !readOnly && story.theme && <button type="button" className="studio-link" onClick={() => onChange(resetTheme(story))}>Reset to defaults</button>}</div>
    {!v2 && <UpgradeNotice readOnly={readOnly} onUpgrade={onUpgrade} />}
    <div className="studio-look-grid">
      <fieldset className="studio-form studio-look-form" disabled={readOnly || !v2}>
        <h3>Text box</h3>
        <Field label="Position"><select value={theme.textbox.position} onChange={event => set("textbox", "position", event.target.value)}>
          <option value="bottom">Bottom</option><option value="middle">Middle</option><option value="top">Top</option></select></Field>
        <Field label={`Width · ${theme.textbox.width}%`}><input type="range" min={40} max={100} value={theme.textbox.width}
          onChange={event => set("textbox", "width", Number(event.target.value))} /></Field>
        {color("textbox", "background", "Background", true)}
        {color("textbox", "text", "Text")}
        {color("textbox", "border", "Border")}
        <Field label={`Corner radius · ${theme.textbox.radius}px`}><input type="range" min={0} max={48} value={theme.textbox.radius}
          onChange={event => set("textbox", "radius", Number(event.target.value))} /></Field>
        <h3>Name box</h3>
        <label className="studio-check"><input type="checkbox" checked={theme.name.show}
          onChange={event => set("name", "show", event.target.checked)} /><span>Show the speaker's name</span></label>
        {color("name", "background", "Background")}
        {color("name", "text", "Text")}
        <p className="studio-hint">A character with its own colour (Characters) fills the name box with it.</p>
        <h3>Choices</h3>
        {color("choices", "background", "Background")}
        {color("choices", "text", "Text")}
        {color("choices", "border", "Border")}
        <h3>Font</h3>
        <Field label="Typeface" hint="Upload static TTF or OTF fonts in Assets.">
          <select value={fontAsset?.id ?? (fontKey ? `story:${fontKey}` : "")} onChange={event => {
            const chosen = fonts.find(asset => asset.id === event.target.value);
            if (!chosen) { set("font", "asset", null); return; }
            try {
              const bound = bindAsset(story, chosen);
              onChange(setThemeValue(bound.story, "font", "asset", bound.key), "theme:font.asset");
            } catch (error) { onError(message(error)); }
          }}>
            <option value="">Lora (built in)</option>
            {fontKey && !fontAsset && <option value={`story:${fontKey}`}>{fontKey}</option>}
            {fonts.map(asset => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
          </select></Field>
        <Field label={`Size · ${theme.font.size}px at 1280×720`}><input type="range" min={14} max={48} value={theme.font.size}
          onChange={event => set("font", "size", Number(event.target.value))} /></Field>
      </fieldset>
      <div className="studio-look-preview">
        <div className="studio-asset-filters" role="group" aria-label="Preview">
          {(["line", "choice"] as const).map(item => <button type="button" key={item} aria-pressed={screen === item}
            className={screen === item ? "selected" : ""} onClick={() => setScreen(item)}>{item === "line" ? "Dialogue" : "Choice"}</button>)}
        </div>
        <StagePreview story={story} theme={theme} screen={screen} tenantId={tenantId} projectId={projectId}
          font={family}
          background={libraryAsset(assets, firstBackground(story))?.id ?? null} />
        <p className="studio-hint">The preview uses the story's first background and first character with sprites.</p>
      </div>
    </div>
  </section>;
}

function StagePreview({ story, theme, screen, tenantId, projectId, font, background }: {
  story: StoryDraft; theme: ResolvedTheme; screen: "line" | "choice"; tenantId: string; projectId: string;
  font: string | null | false; background: string | null;
}) {
  const { assets } = useApprovedAssets(tenantId, projectId);
  const backdrop = useNarrativeImage(tenantId, projectId, background, "image");
  const cast = Object.entries(story.characters).find(([, character]) => Object.keys(character.sprites ?? {}).length);
  const spriteKey = cast ? Object.values(cast[1].sprites ?? {})[0] : undefined;
  const spriteAsset = libraryAsset(assets, spriteKey ? story.assets[spriteKey]?.sha256 : undefined);
  const sprite = useNarrativeImage(tenantId, projectId, spriteAsset?.id ?? null, "image");
  const figure = spriteAsset?.width && spriteAsset.height
    ? figureBox(spriteAsset.width, spriteAsset.height, cast?.[1].stage, SLOT_CENTERS.left) : null;
  const speaker = cast?.[1] ?? Object.values(story.characters)[0];
  const box = theme.textbox, named = theme.name;
  const fill = speaker?.color ?? named.background;
  const ink = speaker?.color ? inkOn(speaker.color) : named.text;
  const scaled = (pixels: number) => `calc(${pixels} * 100cqw / 1280)`;
  const family = font ? `"${font}", "Lora", serif` : `"Lora", serif`;
  const edge = box.position === "top" ? { top: scaled(24 + 44) } : box.position === "middle"
    ? { top: "50%", transform: "translateY(-50%)" } : { bottom: scaled(24) };
  const boxStyle: CSSProperties = {
    ...edge, left: `${(100 - box.width) / 2}%`, width: `${box.width}%`, background: box.background,
    color: box.text, border: `${scaled(2)} solid ${box.border}`, borderRadius: scaled(box.radius),
    fontFamily: family, fontSize: scaled(theme.font.size), minHeight: scaled(theme.font.size * 4.2),
  };
  const choiceTop = box.position === "bottom" ? "40%" : box.position === "top" ? "66%" : "82%";
  return <div className="studio-look-stage" style={backdrop ? { backgroundImage: `url(${backdrop})` } : undefined}
    aria-label="Preview of the game screen" role="img">
    {sprite && figure && <img className="studio-look-sprite" src={sprite} alt="" style={{ left: `${figure.left}%`,
      top: `${figure.top}%`, width: `${figure.width}%`, height: `${figure.height}%` }} />}
    {screen === "choice" && <div className="studio-look-choices" style={{ top: choiceTop }}>
      {["Walk to the end of the pier", "Wait for the bell"].map(label => <span key={label} style={{
        background: theme.choices.background, color: theme.choices.text, border: `${scaled(2)} solid ${theme.choices.border}`,
        borderRadius: scaled(box.radius), fontFamily: family, fontSize: scaled(theme.font.size),
      }}>{label}</span>)}</div>}
    <div className="studio-look-box" style={boxStyle}>
      {named.show && screen === "line" && <span className="studio-look-name" style={{ background: fill, color: ink,
        borderRadius: scaled(Math.max(4, box.radius / 2)), fontSize: scaled(Math.max(12, theme.font.size * 0.8)) }}>
        {speaker?.name ?? "Speaker"}</span>}
      <p>{screen === "line" ? "The lanterns are lit again. Someone must have come back." : "What do you do?"}</p>
    </div>
  </div>;
}
