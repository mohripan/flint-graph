export type PreviewPhase = "waiting" | "loading" | "loaded" | "error";
export function previewOrigin(value: string, parent: string): string {
  const child = new URL(value), app = new URL(parent);
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(child.hostname);
  if (child.origin !== value || child.username || child.password || child.hostname === app.hostname
    || (child.protocol !== "https:" && !(child.protocol === "http:" && loopback)))
    throw new Error("Playtest needs a separate trusted host. Configure the preview origin.");
  return child.origin;
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
