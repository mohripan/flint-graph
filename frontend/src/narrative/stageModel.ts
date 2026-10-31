// Editor operations for story format 2 (ADR 0040): library assets bound into the story,
// the theme, a scene's opening stage step, line expressions and character sprites.
// Everything edits the same story nodes the runtimes play; the server validates saves.
import type { CharacterFraming, StagePosition, StageShow, StoryDraft, StoryNode, StoryTheme } from "./types";

type StageNode = Extract<StoryNode, { type: "stage" }>;
/** Describe the effective image without writing inherited state into the story. */
export function stageImageChoice(value: string | null | undefined, inherited: string | null | undefined): { key: string | null; label: string } {
  if (value !== undefined) return { key: value, label: value ?? "None" };
  if (inherited === "?") return { key: null, label: "Varies by path" };
  return { key: inherited ?? null, label: inherited ? `From earlier scenes: ${inherited}` : "None from earlier scenes" };
}
export const POSITIONS: StagePosition[] = ["left", "center", "right"];
const ID = /^[a-z][a-z0-9_-]{0,63}$/;
const RESERVED = new Set(["con", "prn", "aux", "nul",
  ...Array.from({ length: 9 }, (_, index) => `com${index + 1}`), ...Array.from({ length: 9 }, (_, index) => `lpt${index + 1}`)]);

const has = (record: object, key: string) => Object.prototype.hasOwnProperty.call(record, key);
function available(base: string, used: (key: string) => boolean): string {
  if (!used(base)) return base;
  let number = 2;
  while (used(`${base}_${number}`)) number += 1;
  return `${base}_${number}`;
}

// ---- Library assets bound by SHA-256 ----------------------------------------------------

export interface LibraryAsset { sha256: string; media_type: string; name: string }
const EXTENSIONS: Record<string, string> = { "image/png": "png", "font/ttf": "ttf", "font/otf": "otf", "audio/wav": "wav" };
const KINDS: Record<string, "image" | "font" | "audio"> = { png: "image", ttf: "font", otf: "font", wav: "audio" };

export function slug(name: string): string {
  let text = name.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 56).replace(/_+$/, "");
  if (!/^[a-z]/.test(text)) text = `asset_${text}`.replace(/_+$/, "");
  return RESERVED.has(text) ? `asset_${text}` : text;
}

/** The story asset that already names these exact bytes, if any. */
export function assetKeyFor(story: StoryDraft, sha256: string): string | undefined {
  return Object.entries(story.assets).find(([, item]) => item.sha256 === sha256)?.[0];
}

/** Reuse or add the story asset for a library file: one key per file, named after it. */
export function bindAsset(story: StoryDraft, asset: LibraryAsset): { story: StoryDraft; key: string } {
  const extension = EXTENSIONS[asset.media_type];
  if (!extension) throw new Error("Only PNG images, TTF/OTF fonts and WAV voice clips can be used in a story.");
  const kind = KINDS[extension];
  const existing = Object.entries(story.assets).find(([, item]) =>
    item.sha256 === asset.sha256 && (item.kind ?? "image") === kind && item.path.endsWith(`.${extension}`));
  if (existing) return { story, key: existing[0] };
  if (Object.keys(story.assets).length >= 256) throw new Error("A story can use at most 256 assets.");
  const key = available(slug(asset.name) || kind, candidate => has(story.assets, candidate));
  return { key, story: { ...story, assets: { ...story.assets,
    [key]: { kind, path: `assets/${key}.${extension}`, sha256: asset.sha256 } } } };
}

export function usedAssets(story: StoryDraft): Set<string> {
  const used = new Set<string>();
  for (const node of Object.values(story.nodes)) {
    if (node.type === "stage" && typeof node.background === "string") used.add(node.background);
    if (node.type === "stage" && typeof node.cg === "string") used.add(node.cg);
    if (node.type === "line" && node.voice?.audio) used.add(node.voice.audio);
  }
  for (const character of Object.values(story.characters)) {
    for (const key of Object.values(character.sprites ?? {})) used.add(key);
  }
  if (story.theme?.font?.asset) used.add(story.theme.font.asset);
  return used;
}

/** Drop story assets nothing refers to any more, so a game never ships stray files. */
export function pruneAssets(story: StoryDraft): StoryDraft {
  const used = usedAssets(story);
  const kept = Object.entries(story.assets).filter(([key]) => used.has(key));
  return kept.length === Object.keys(story.assets).length ? story : { ...story, assets: Object.fromEntries(kept) };
}

// ---- Theme ------------------------------------------------------------------------------

export const THEME_DEFAULTS = {
  textbox: { position: "bottom", width: 92, background: "#182635e6", text: "#f0f4f6", border: "#d5ae68", radius: 12 },
  name: { show: true, background: "#d5ae68", text: "#182635" },
  choices: { background: "#f0f4f6", text: "#182635", border: "#d5ae68" },
  font: { asset: null as string | null, size: 22 },
};
export type ResolvedTheme = typeof THEME_DEFAULTS;
type Part = keyof ResolvedTheme;

export function resolvedTheme(story: StoryDraft): ResolvedTheme {
  const theme = story.theme ?? {};
  return {
    textbox: { ...THEME_DEFAULTS.textbox, ...theme.textbox },
    name: { ...THEME_DEFAULTS.name, ...theme.name },
    choices: { ...THEME_DEFAULTS.choices, ...theme.choices },
    font: { ...THEME_DEFAULTS.font, ...theme.font },
  };
}

/** Set one theme field; values equal to the default are left out of the story. */
export function setThemeValue<P extends Part>(story: StoryDraft, part: P, field: keyof ResolvedTheme[P],
  value: string | number | boolean | null): StoryDraft {
  const theme: Record<string, Record<string, unknown>> = structuredClone(story.theme ?? {}) as Record<string, Record<string, unknown>>;
  const section = { ...(theme[part] ?? {}) };
  if ((THEME_DEFAULTS[part] as Record<string, unknown>)[field as string] === value) delete section[field as string];
  else section[field as string] = value;
  if (Object.keys(section).length) theme[part] = section; else delete theme[part];
  const { theme: _, ...rest } = story;
  return pruneAssets(Object.keys(theme).length ? { ...rest, theme: theme as StoryTheme } : rest);
}

export function resetTheme(story: StoryDraft): StoryDraft {
  const { theme: _, ...rest } = story;
  return pruneAssets(rest);
}

export function splitColor(value: string): { rgb: string; alpha: number } {
  return { rgb: value.slice(0, 7), alpha: value.length === 9 ? parseInt(value.slice(7), 16) : 255 };
}
export function joinColor(rgb: string, alpha: number): string {
  const clamped = Math.max(0, Math.min(255, Math.round(alpha)));
  return clamped === 255 ? rgb.toLowerCase() : `${rgb.toLowerCase()}${clamped.toString(16).padStart(2, "0")}`;
}
/** Readable text on a name box filled with a character's colour, as the runtime picks it. */
export function inkOn(color: string): string {
  const [r, g, b] = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255);
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return luminance > 0.5 ? "#182635" : "#f0f4f6";
}

// ---- What is on stage when each node is reached -------------------------------------------

export type Placed = { position: StagePosition; sprite: string; x?: number };
export interface StageSnapshot { background: string | null | "?"; cg: string | null | "?"; characters: Record<string, Placed | "?"> }
const EMPTY: StageSnapshot = { background: null, cg: null, characters: {} };

export function applyStageNode(state: StageSnapshot, node: StoryNode): StageSnapshot {
  if (node.type === "stage") {
    const characters: Record<string, Placed | "?"> = {};
    for (const [id, value] of Object.entries(state.characters)) if (!node.hide?.includes(id)) characters[id] = value;
    for (const entry of node.show ?? []) {
      for (const [id, value] of Object.entries(characters)) {
        if (value !== "?" && value.position === entry.position && id !== entry.character) delete characters[id];
      }
      characters[entry.character] = { position: entry.position, sprite: entry.sprite, ...(entry.x !== undefined ? { x: entry.x } : {}) };
    }
    return { background: node.background !== undefined ? node.background : state.background,
      cg: node.cg !== undefined ? node.cg : state.cg, characters };
  }
  if (node.type === "line" && node.expression && node.speaker) {
    const placed = state.characters[node.speaker];
    if (placed && placed !== "?") {
      return { ...state, characters: { ...state.characters, [node.speaker]: { ...placed, sprite: node.expression } } };
    }
  }
  return state;
}

function join(left: StageSnapshot, right: StageSnapshot): StageSnapshot {
  const characters: Record<string, Placed | "?"> = {};
  for (const id of new Set([...Object.keys(left.characters), ...Object.keys(right.characters)])) {
    const a = left.characters[id], b = right.characters[id];
    characters[id] = a && b && JSON.stringify(a) === JSON.stringify(b) ? a : "?";
  }
  return { background: left.background === right.background ? left.background : "?",
    cg: left.cg === right.cg ? left.cg : "?", characters };
}

function targets(node: StoryNode): string[] {
  switch (node.type) {
    case "line": case "set": case "stage": return [node.next];
    case "choice": return node.options.map(option => option.target);
    case "branch": return [node.if_true, node.if_false];
    case "end": return [];
  }
}

/** Stable first-use order across canonical JSON: entry-first DFS, then orphan node IDs. */
export function cgGalleryAssets(story: StoryDraft): string[] {
  if (story.schema_version !== "2") return [];
  const pending = [...Object.keys(story.nodes).sort().reverse(), story.entry];
  const visited = new Set<string>(), assets = new Set<string>();
  while (pending.length) {
    const id = pending.pop()!;
    if (visited.has(id)) continue;
    visited.add(id);
    const node = story.nodes[id];
    if (!node) continue;
    if (node.type === "stage" && typeof node.cg === "string") assets.add(node.cg);
    pending.push(...targets(node).reverse());
  }
  return [...assets];
}

/** The stage as each reachable node begins; paths that disagree give "?" (varies). */
export function stageBefore(story: StoryDraft): Map<string, StageSnapshot> {
  const states = new Map<string, StageSnapshot>();
  if (!has(story.nodes, story.entry)) return states;
  states.set(story.entry, EMPTY);
  const pending = [story.entry];
  let budget = 200000;
  while (pending.length && budget-- > 0) {
    const id = pending.shift()!;
    const node = story.nodes[id];
    if (!node) continue;
    const after = applyStageNode(states.get(id)!, node);
    for (const target of targets(node)) {
      if (!has(story.nodes, target)) continue;
      const previous = states.get(target);
      const joined = previous ? join(previous, after) : after;
      if (!previous || JSON.stringify(previous) !== JSON.stringify(joined)) {
        states.set(target, joined);
        pending.push(target);
      }
    }
  }
  return states;
}

export function describeSnapshot(story: StoryDraft, snapshot: StageSnapshot | undefined): string[] {
  if (!snapshot) return ["Not reached from the start"];
  const name = (id: string) => story.characters[id]?.name || id;
  const parts = [snapshot.background === "?" ? "Background varies by path"
    : snapshot.background === null ? "No background" : `Background ${snapshot.background}`];
  if (snapshot.cg !== null) parts.push(snapshot.cg === "?" ? "CG varies by path" : `CG ${snapshot.cg}`);
  const placed = Object.entries(snapshot.characters).sort(([, a], [, b]) =>
    (a === "?" ? 3 : POSITIONS.indexOf(a.position)) - (b === "?" ? 3 : POSITIONS.indexOf(b.position)));
  for (const [id, value] of placed) {
    parts.push(value === "?" ? `${name(id)}: varies by path` : `${name(id)} (${value.sprite}) at ${value.position}`);
  }
  return parts;
}

// ---- A scene's opening stage step --------------------------------------------------------

export interface StageEdit { background?: string | null; cg?: string | null; show: StageShow[]; hide: string[] }

export function sceneStage(story: StoryDraft, head: string): StageEdit {
  const node = story.nodes[head];
  if (node?.type !== "stage") return { show: [], hide: [] };
  return { ...(node.background !== undefined ? { background: node.background } : {}),
    ...(node.cg !== undefined ? { cg: node.cg } : {}),
    show: node.show ?? [], hide: node.hide ?? [] };
}

export function stageProblem(edit: StageEdit): string | null {
  const shown = edit.show.map(entry => entry.character);
  if (new Set(shown).size !== shown.length) return "A character can only be placed once.";
  const places = edit.show.map(entry => entry.position);
  if (new Set(places).size !== places.length) return "Two characters cannot share a position.";
  if (edit.hide.some(id => shown.includes(id))) return "A character cannot leave and be placed in the same step.";
  if (edit.show.length > 8 || edit.hide.length > 8) return "A stage step changes at most eight characters.";
  return null;
}

function retarget(story: StoryDraft, from: string, to: string): StoryDraft {
  const follow = (target: string) => target === from ? to : target;
  const nodes: Record<string, StoryNode> = {};
  for (const [key, item] of Object.entries(story.nodes)) {
    nodes[key] = item.type === "line" || item.type === "set" || item.type === "stage" ? { ...item, next: follow(item.next) }
      : item.type === "choice" ? { ...item, options: item.options.map(option => ({ ...option, target: follow(option.target) })) }
      : item.type === "branch" ? { ...item, if_true: follow(item.if_true), if_false: follow(item.if_false) } : item;
  }
  return { ...story, entry: follow(story.entry), nodes };
}

/** Write (or remove) the stage step that opens a scene, keeping the scene's ID and routes. */
export function setSceneStage(story: StoryDraft, head: string, edit: StageEdit): StoryDraft {
  if (edit.cg !== undefined) {
    if (story.schema_version !== "2") throw new Error("unknown_field: cg needs story format 2.");
    if (edit.cg !== null) {
      if (typeof edit.cg !== "string" || !ID.test(edit.cg)) throw new Error("invalid_id: cg");
      if (!has(story.assets, edit.cg)) throw new Error("unknown_reference: cg");
      if (story.assets[edit.cg].kind !== "image") throw new Error("invalid_asset_kind: cg");
    }
  }
  const problem = stageProblem(edit);
  if (problem) throw new Error(problem);
  const current = story.nodes[head];
  if (!current) throw new Error("Scene no longer exists.");
  const effect = edit.background !== undefined || edit.cg !== undefined || edit.show.length > 0 || edit.hide.length > 0;
  const step = (next: string): StageNode => ({ type: "stage",
    ...(edit.background !== undefined ? { background: edit.background } : {}),
    ...(edit.cg !== undefined ? { cg: edit.cg } : {}),
    ...(edit.hide.length ? { hide: edit.hide } : {}), ...(edit.show.length ? { show: edit.show } : {}), next });
  if (current.type === "stage") {
    if (effect) return pruneAssets({ ...story, nodes: { ...story.nodes, [head]: step(current.next) } });
    // Fold the following step back under the scene's ID so its folder and routes stay put.
    if (current.next === head || !story.nodes[current.next]) throw new Error("This stage step has nowhere to continue.");
    const following = current.next;
    const nodes = { ...story.nodes, [head]: story.nodes[following] };
    delete nodes[following];
    return pruneAssets(retarget({ ...story, nodes }, following, head));
  }
  if (!effect) return story;
  if (Object.keys(story.nodes).length >= 10000) throw new Error("This story already has 10,000 scenes.");
  // The stage step takes the scene's ID; what used to open the scene moves right after it.
  const moved = available(`${head.slice(0, 56)}_open`, key => has(story.nodes, key));
  return pruneAssets({ ...story, nodes: { ...story.nodes, [moved]: current, [head]: step(moved) } });
}

// ---- Lines and characters ----------------------------------------------------------------

export function setLineSpeaker(story: StoryDraft, id: string, speaker: string | null): StoryDraft {
  const node = story.nodes[id];
  if (node?.type !== "line") throw new Error("Only lines have a speaker.");
  const { speaker: _, expression, ...rest } = node;
  const sprites = speaker ? story.characters[speaker]?.sprites ?? {} : {};
  const keep = expression && has(sprites, expression) ? { expression } : {};
  return { ...story, nodes: { ...story.nodes, [id]: speaker ? { ...rest, speaker, ...keep } : rest } };
}

export function setLineExpression(story: StoryDraft, id: string, expression: string | null): StoryDraft {
  const node = story.nodes[id];
  if (node?.type !== "line" || (expression && !node.speaker)) throw new Error("Choose who speaks before an expression.");
  const { expression: _, ...rest } = node;
  return { ...story, nodes: { ...story.nodes, [id]: expression ? { ...rest, expression } : rest } };
}

export function spriteUses(story: StoryDraft, character: string, expression: string): number {
  let count = 0;
  for (const node of Object.values(story.nodes)) {
    if (node.type === "line" && node.speaker === character && node.expression === expression) count += 1;
    if (node.type === "stage") count += (node.show ?? []).filter(entry => entry.character === character && entry.sprite === expression).length;
  }
  return count;
}

export function setSprite(story: StoryDraft, character: string, expression: string, key: string): StoryDraft {
  const current = story.characters[character];
  if (!current) throw new Error("Character no longer exists.");
  if (!ID.test(expression)) throw new Error("Name expressions with lowercase letters, digits, - or _, starting with a letter.");
  const sprites = { ...current.sprites, [expression]: key };
  if (Object.keys(sprites).length > 32) throw new Error("A character can have at most 32 expressions.");
  return pruneAssets({ ...story, characters: { ...story.characters, [character]: { ...current, sprites } } });
}

export function removeSprite(story: StoryDraft, character: string, expression: string): StoryDraft {
  const current = story.characters[character];
  if (!current?.sprites || !has(current.sprites, expression)) throw new Error("Expression no longer exists.");
  const uses = spriteUses(story, character, expression);
  if (uses) throw new Error(`This expression is used ${uses === 1 ? "once" : `${uses} times`} in the story. Change those first.`);
  const sprites = { ...current.sprites }; delete sprites[expression];
  const { sprites: _, ...rest } = current;
  return pruneAssets({ ...story, characters: { ...story.characters,
    [character]: Object.keys(sprites).length ? { ...rest, sprites } : rest } });
}

export function setCharacterColor(story: StoryDraft, character: string, color: string | null): StoryDraft {
  const current = story.characters[character];
  if (!current) throw new Error("Character no longer exists.");
  const { color: _, ...rest } = current;
  return { ...story, characters: { ...story.characters, [character]: color ? { ...rest, color: color.toLowerCase() } : rest } };
}

// ---- Framing on stage (runtime 0.4.0) -------------------------------------------------------

export const SLOT_CENTERS: Record<StagePosition, number> = { left: 20, center: 50, right: 80 };
export const DEFAULT_SCALE = 92;

/** A character's size and top on stage; null restores the fit-to-slot default. */
export function setCharacterFraming(story: StoryDraft, character: string, framing: CharacterFraming | null): StoryDraft {
  const current = story.characters[character];
  if (!current) throw new Error("Character no longer exists.");
  const { stage: _, ...rest } = current;
  if (framing?.scale !== undefined && (!Number.isInteger(framing.scale) || framing.scale < 40 || framing.scale > 300)) {
    throw new Error("Size on stage must be between 40% and 300%.");
  }
  if (framing?.top !== undefined && (!Number.isInteger(framing.top) || framing.top < -50 || framing.top > 100)) {
    throw new Error("The top edge must be between -50% and 100%.");
  }
  const kept = framing ? Object.fromEntries(Object.entries(framing).filter(([, value]) => value !== undefined)) : {};
  return { ...story, characters: { ...story.characters,
    [character]: Object.keys(kept).length ? { ...rest, stage: kept } : rest } };
}

/** Where a sprite is drawn, in % of a 16:9 stage, by the same rules as the Godot stage view. */
export function figureBox(width: number, height: number, framing: CharacterFraming | undefined, center: number):
  { left: number; top: number; width: number; height: number } {
  const stageWidth = 1280, stageHeight = 720;
  let drawnWidth: number, drawnHeight: number, top: number;
  if (!framing || (framing.scale === undefined && framing.top === undefined)) {
    const factor = Math.min(stageWidth * 0.36 / width, stageHeight * 0.92 / height);
    drawnWidth = width * factor; drawnHeight = height * factor; top = stageHeight - drawnHeight;
  } else {
    const scale = framing.scale ?? DEFAULT_SCALE;
    drawnHeight = stageHeight * scale / 100; drawnWidth = width * drawnHeight / height;
    top = stageHeight * (framing.top ?? Math.max(0, 100 - scale)) / 100;
  }
  return { left: (center / 100 * stageWidth - drawnWidth / 2) / stageWidth * 100, top: top / stageHeight * 100,
    width: drawnWidth / stageWidth * 100, height: drawnHeight / stageHeight * 100 };
}

/** Expression IDs a creator types, made valid and unique for the character. */
export function expressionId(story: StoryDraft, character: string, wanted: string): string {
  const base = slug(wanted || "expression").replace(/^asset_/, "") || "expression";
  const id = /^[a-z]/.test(base) ? base : `e_${base}`;
  return available(id.slice(0, 60), key => has(story.characters[character]?.sprites ?? {}, key));
}

// Player terms (ADR 0044, runtime 0.7.0): some voice model licenses require a game to put
// terms on its players. The server writes them into the generated part of NOTICES; every
// runtime finds them the same way, after the asset-notices marker only.
export const NOTICE_MARKER = "=== Asset notices (generated by FlintGraph; edits below this line are replaced) ===";
export const TERMS_BEGIN = "=== Player terms (shown once to players by the game) ===";
export const TERMS_END = "=== End of player terms ===";
const TERMS_LIMIT = 64 * 1024;

/** The terms a game shows its players before play, or null; throws on a malformed block. */
export function playerTerms(notices: string): string | null {
  const lines = notices.split("\n");
  const marker = lines.indexOf(NOTICE_MARKER);
  if (marker < 0) return null;
  const generated = lines.slice(marker + 1);
  const begin = generated.indexOf(TERMS_BEGIN);
  if (begin < 0) {
    if (generated.includes(TERMS_END)) throw new Error("invalid_notices");
    return null;
  }
  const rest = generated.slice(begin + 1);
  const end = rest.indexOf(TERMS_END);
  if (end < 0 || rest.includes(TERMS_BEGIN)) throw new Error("invalid_notices");
  const after = rest.slice(end + 1);
  if (after.includes(TERMS_END) || after.some(line => line.trim())) throw new Error("invalid_notices");
  const terms = rest.slice(0, end).join("\n").replace(/^\n+|\n+$/g, "");
  if (!terms.trim() || new TextEncoder().encode(terms).length > TERMS_LIMIT) throw new Error("invalid_notices");
  return terms;
}
