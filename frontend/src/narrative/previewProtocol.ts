export type PreviewPhase = "waiting" | "loading" | "loaded" | "error";
export function previewOrigin(value: string, parent: string): string {
  const child = new URL(value), app = new URL(parent);
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(child.hostname);
  if (child.origin !== value || child.username || child.password || child.hostname === app.hostname
    || (child.protocol !== "https:" && !(child.protocol === "http:" && loopback)))
    throw new Error("Playtest needs a separate trusted host. Configure the preview origin.");
  return child.origin;
}
// Story format 2 (ADR 0040): playtests carry the revision's image and font bytes.
export const ASSET_CAPS = { image: 10485760, font: 8388608 } as const;
export const ASSET_TOTAL = 104857600;
export interface StoryAssetRef { kind: string; path: string; sha256: string }
export type Digest = (data: ArrayBuffer) => Promise<string>;
export const sha256Hex: Digest = async data =>
  [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))].map(value => value.toString(16).padStart(2, "0")).join("");
export function storyAssets(storyJson: string): Record<string, StoryAssetRef> | null {
  const story = JSON.parse(storyJson) as { schema_version?: string; assets?: Record<string, StoryAssetRef> };
  return story.schema_version === "2" ? story.assets ?? {} : null;
}
/** Every declared asset, within its cap, with exactly its hash; nothing else. */
export async function checkedAssets(declared: Record<string, StoryAssetRef>, fetched: Record<string, ArrayBuffer>,
  digest: Digest = sha256Hex): Promise<Record<string, ArrayBuffer>> {
  const ids = Object.keys(declared).sort();
  if (ids.length > 256 || ids.length !== Object.keys(fetched).length
    || ids.some(id => !Object.prototype.hasOwnProperty.call(fetched, id)))
    throw new Error("The revision's assets do not match its story.");
  let total = 0;
  for (const id of ids) {
    const cap = ASSET_CAPS[declared[id].kind as keyof typeof ASSET_CAPS];
    total += fetched[id].byteLength;
    if (!cap || fetched[id].byteLength > cap || total > ASSET_TOTAL)
      throw new Error("The revision's assets are larger than a playtest can load.");
    if (await digest(fetched[id]) !== declared[id].sha256) throw new Error("An asset changed after it was saved.");
  }
  return Object.fromEntries(ids.map(id => [id, fetched[id]]));
}
/** The load message and its transfer list; v1 revisions keep message version 1. */
export function snapshotMessage(nonce: string, revision: { id: string; content_hash: string; story_json: string; notices: string },
  assets: Record<string, ArrayBuffer> | null): { message: Record<string, unknown>; transfer: ArrayBuffer[] } {
  const message: Record<string, unknown> = { protocol: "flint-preview", version: assets ? 2 : 1, nonce, type: "load-snapshot",
    revision_id: revision.id, content_hash: revision.content_hash, story_json: revision.story_json, notices: revision.notices };
  if (assets) message.assets = assets;
  return { message, transfer: assets ? Object.values(assets) : [] };
}
interface Context { window: unknown; origin: string; nonce: string; revision: string; hash: string }
export function acceptPreviewMessage(event: { source: unknown; origin: string; data: unknown },
  context: Context, phase: PreviewPhase): "ready" | "loaded" | "error" | "close" | null {
  if (event.source !== context.window || event.origin !== context.origin) return null;
  const data = event.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const item = data as Record<string, unknown>;
  if (item.protocol !== "flint-preview" || item.version !== 1 || item.nonce !== context.nonce) return null;
  const base = ["protocol", "version", "nonce", "type"];
  const exact = (keys: string[]) => Object.keys(item).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(item, key));
  if (item.type === "close" && exact(base)) return "close";
  if (item.type === "ready" && phase === "waiting" && exact(base)) return "ready";
  if ((item.type === "loaded" || item.type === "error") && phase === "loading"
    && exact([...base, "revision_id", "content_hash"]) && item.revision_id === context.revision
    && item.content_hash === context.hash) return item.type;
  return null;
}
