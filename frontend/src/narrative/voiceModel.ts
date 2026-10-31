// Voiced lines (ADR 0043): a line is silent, fully voiced or marked by a short sound
// such as "fufu". The choice lives on the story line; a clip is an approved library
// voice asset bound by SHA-256. Mirrors the format rules the runtimes check.
import { bindAsset, pruneAssets } from "./stageModel";
import type { LibraryAsset } from "./stageModel";
import type { LineVoice, StoryDraft, StoryNode } from "./types";

export type VoiceChoice = "silent" | "full" | "vocalization";
export const VOCALIZATION_LIMIT = 40;
export const VOCALIZATION_EXAMPLES = ["fufu", "hmm", "ah", "ehehe", "huh?"];
type Line = Extract<StoryNode, { type: "line" }>;
const ID = /^[a-z][a-z0-9_-]{0,63}$/;
const has = (record: object, key: string) => Object.prototype.hasOwnProperty.call(record, key);
const isBlank = (value: string) => !value.trim();

function line(story: StoryDraft, id: string): Line {
  const node = story.nodes[id];
  if (node?.type !== "line") throw new Error("Only lines can be voiced.");
  return node;
}

function withVoice(story: StoryDraft, id: string, voice: LineVoice | null): StoryDraft {
  const { voice: _, ...rest } = line(story, id);
  return pruneAssets({ ...story, nodes: { ...story.nodes, [id]: voice ? { ...rest, voice } : rest } });
}

export function voiceChoice(node: StoryNode | undefined): VoiceChoice {
  return node?.type === "line" && node.voice ? node.voice.mode : "silent";
}

/** The first problem with a line's voice, with the validator's code and location. */
export function voiceProblem(story: StoryDraft, id: string): { code: string; location: string } | null {
  const node = story.nodes[id];
  if (node?.type !== "line" || !has(node, "voice")) return null;
  const location = `nodes.${id}.voice`;
  const value: unknown = node.voice;
  if (!value || typeof value !== "object" || Array.isArray(value)) return { code: "invalid_object", location };
  const voice = value as Record<string, unknown>;
  if (Object.keys(voice).some(key => !["mode", "text", "audio"].includes(key))) return { code: "unknown_field", location };
  if (!has(voice, "mode")) return { code: "missing_field", location };
  if (voice.mode !== "full" && voice.mode !== "vocalization") return { code: "invalid_value", location: `${location}.mode` };
  if (!node.speaker) return { code: "invalid_voice", location };
  if ((voice.mode === "vocalization") !== has(voice, "text")) return { code: "invalid_voice", location };
  if (has(voice, "text")) {
    const text = voice.text;
    if (typeof text !== "string" || isBlank(text) || [...text].length > VOCALIZATION_LIMIT)
      return { code: "invalid_text", location: `${location}.text` };
  }
  if (has(voice, "audio")) {
    const audio = voice.audio;
    if (typeof audio !== "string" || !ID.test(audio)) return { code: "invalid_id", location: `${location}.audio` };
    if (!has(story.assets, audio)) return { code: "unknown_reference", location: `${location}.audio` };
    if (story.assets[audio].kind !== "audio") return { code: "invalid_asset_kind", location: `${location}.audio` };
  }
  return null;
}

/** What a player plays on this screen: the settled line's clip, else nothing. */
export function lineClip(story: StoryDraft, id: string): string | null {
  const node = story.nodes[id];
  return node?.type === "line" ? node.voice?.audio ?? null : null;
}

export function setLineVoice(story: StoryDraft, id: string, choice: VoiceChoice, sound?: string): StoryDraft {
  const node = line(story, id);
  if (choice === "silent") return withVoice(story, id, null);
  if (!node.speaker) throw new Error("Choose who speaks before giving the line a voice.");
  const current = node.voice;
  if (choice === "full") {
    return withVoice(story, id, current?.mode === "full" ? current : { mode: "full" });
  }
  const text = (sound ?? current?.text ?? VOCALIZATION_EXAMPLES[0]).split(/\s+/).filter(Boolean).join(" ");
  if (!text) throw new Error("Type the sound, for example “fufu” or “hmm”.");
  if ([...text].length > VOCALIZATION_LIMIT) throw new Error(`Keep the sound to ${VOCALIZATION_LIMIT} characters.`);
  const keep = current?.mode === "vocalization" && current.audio ? { audio: current.audio } : {};
  return withVoice(story, id, { mode: "vocalization", text, ...keep });
}

/** Bind an approved voice clip from the library to the line, or remove its clip. */
export function setLineClip(story: StoryDraft, id: string, clip: LibraryAsset | null): StoryDraft {
  const node = line(story, id);
  if (!node.voice) throw new Error("Choose full voice or a vocalization first.");
  const { audio: _, ...rest } = node.voice;
  if (!clip) return withVoice(story, id, rest);
  const bound = bindAsset(story, clip);
  return withVoice(bound.story, id, { ...rest, audio: bound.key });
}

/** After a speaker change: narration is silent, and another character's clip is dropped. */
export function withSpeaker(story: StoryDraft, before: StoryDraft, id: string): StoryDraft {
  const node = line(story, id), previous = before.nodes[id];
  if (!node.voice) return story;
  if (!node.speaker) return withVoice(story, id, null);
  if (previous?.type === "line" && previous.speaker !== node.speaker && node.voice.audio) {
    const { audio: _, ...rest } = node.voice;
    return withVoice(story, id, rest);
  }
  return story;
}

/** The text a clip for this line speaks: the line itself, or the vocalization. */
export function spokenText(story: StoryDraft, id: string): string {
  const node = line(story, id);
  return node.voice?.mode === "vocalization" ? node.voice.text ?? "" : node.text.split(/\s+/).filter(Boolean).join(" ");
}

export interface ClipRequest { mode: "full" | "vocalization"; text: string; node_id: string }

/** Voiced lines without a clip, grouped by speaker: one generation job each. */
export function missingClips(story: StoryDraft, ids: string[]): Record<string, ClipRequest[]> {
  const grouped: Record<string, ClipRequest[]> = {};
  for (const id of ids) {
    const node = story.nodes[id];
    if (node?.type !== "line" || !node.voice || node.voice.audio || !node.speaker) continue;
    const text = spokenText(story, id);
    if (!text || text.length > 600) continue;
    (grouped[node.speaker] ??= []).push({ mode: node.voice.mode, text, node_id: id });
  }
  return grouped;
}

/** A generated clip whose words no longer match the line (uploads are never stale). */
export function clipIsStale(story: StoryDraft, id: string, clip: { provenance: Record<string, unknown> }): boolean {
  const made = clip.provenance;
  if (typeof made.text !== "string" || typeof made.mode !== "string") return false;
  const node = line(story, id);
  return made.mode !== (node.voice?.mode ?? "") || made.text !== spokenText(story, id);
}
