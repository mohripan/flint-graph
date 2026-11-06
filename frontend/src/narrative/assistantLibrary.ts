// What the creator can attach to a message from the project's library (ADR 0062).
import type { NarrativeImage } from "../lib/api";
import type { StoryDraft } from "./types";

export const MAX_ATTACHMENTS = 12;
export type LibraryTab = "characters" | "pictures" | "voices";
export interface Attachment {
  kind: "character" | "asset"; id: string; name: string; asset_kind: string | null;
}

const PICTURES = new Set(["background", "sprite", "image", "character_portrait"]);
const asChoice = (asset: NarrativeImage): Attachment => ({ kind: "asset", id: asset.id, name: asset.name, asset_kind: asset.kind });

/** The items of one tab that match a search. */
export function libraryChoices(story: Pick<StoryDraft, "characters"> | null, assets: NarrativeImage[] | null,
  tab: LibraryTab, search: string): Attachment[] {
  const wanted = search.trim().toLowerCase();
  const named = (id: string | null) => (id && story?.characters[id]?.name) || "";
  const matches = (...texts: string[]) => !wanted || texts.some(text => text.toLowerCase().includes(wanted));
  if (tab === "characters") {
    return Object.entries(story?.characters ?? {}).filter(([id, item]) => matches(item.name, id))
      .map(([id, item]) => ({ kind: "character", id, name: item.name || id, asset_kind: null }));
  }
  const kinds = tab === "pictures" ? PICTURES : new Set(["voice"]);
  return (assets ?? []).filter(asset => kinds.has(asset.kind)
    && matches(asset.name, asset.character_id ?? "", named(asset.character_id))).map(asChoice);
}

const same = (left: Pick<Attachment, "kind" | "id">, right: Pick<Attachment, "kind" | "id">) =>
  left.kind === right.kind && left.id === right.id;
export function isAttached(attached: Attachment[], item: Pick<Attachment, "kind" | "id">): boolean {
  return attached.some(known => same(known, item));
}
export function toggleAttachment(attached: Attachment[], item: Attachment): Attachment[] {
  if (isAttached(attached, item)) return attached.filter(known => !same(known, item));
  return attached.length >= MAX_ATTACHMENTS ? attached : [...attached, item];
}

const KIND_NAMES: Record<string, string> = {
  background: "Background", sprite: "Sprite", image: "Picture", character_portrait: "Portrait", voice: "Voice",
};
export function attachmentKind(item: Pick<Attachment, "kind" | "asset_kind">): string {
  return item.kind === "character" ? "Character" : KIND_NAMES[item.asset_kind ?? ""] ?? "File";
}
