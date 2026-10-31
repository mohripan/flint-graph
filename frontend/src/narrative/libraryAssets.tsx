import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { NarrativeImage } from "../lib/api";
import { fontFamily } from "./assetModel";
import { useNarrativeImage } from "./characterImages";

// Approved library assets for the story pickers (backgrounds, sprites, fonts). One list
// per project, shared by every picker and refreshed whenever the library changes.
const PAGE = 48, MAX_PAGES = 8;
const lists = new Map<string, Promise<NarrativeImage[]>>();
const listeners = new Set<() => void>();

async function fetchApproved(tenantId: string, projectId: string): Promise<NarrativeImage[]> {
  const assets: NarrativeImage[] = [];
  let before: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const listed = await api.listNarrativeAssets(tenantId, projectId, { status: "approved", limit: PAGE, before });
    assets.push(...listed.assets);
    if (!listed.next_before) break;
    before = listed.next_before;
  }
  return assets;
}

/** Call after approving, uploading or discarding so pickers show the change. */
export function refreshLibrary(): void {
  lists.clear();
  for (const listener of listeners) listener();
}

export function useApprovedAssets(tenantId: string, projectId: string): { assets: NarrativeImage[] | null; failed: boolean } {
  const [state, setState] = useState<{ assets: NarrativeImage[] | null; failed: boolean }>({ assets: null, failed: false });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const listener = () => setVersion(value => value + 1);
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);
  useEffect(() => {
    if (!tenantId || !projectId) return;
    const key = `${tenantId}:${projectId}`;
    let pending = lists.get(key);
    if (!pending) {
      pending = fetchApproved(tenantId, projectId);
      lists.set(key, pending);
      pending.catch(() => lists.delete(key));
    }
    let live = true;
    pending.then(assets => { if (live) setState({ assets, failed: false }); },
      () => { if (live) setState({ assets: [], failed: true }); });
    return () => { live = false; };
  }, [tenantId, projectId, version]);
  return state;
}

export const IMAGE_KINDS = new Set(["background", "image"]);
export const SPRITE_KINDS = new Set(["sprite", "image", "character_portrait"]);

/** The library asset behind a story asset (same bytes), when it is still approved. */
export function libraryAsset(assets: NarrativeImage[] | null, sha256: string | undefined): NarrativeImage | undefined {
  return sha256 ? assets?.find(asset => asset.sha256 === sha256) : undefined;
}

export function AssetThumb({ tenantId, projectId, asset, label }: {
  tenantId: string; projectId: string; asset: NarrativeImage | undefined; label: string;
}) {
  const url = useNarrativeImage(tenantId, projectId, asset?.id ?? null, "thumbnail");
  return <span className={`studio-thumb ${asset?.kind ?? ""}`} title={label}>
    {url ? <img src={url} alt="" /> : <span>{asset ? "…" : label}</span>}</span>;
}

const loadedFonts = new Map<string, Promise<boolean>>();

/** Loads a library font for previews; the CSS family name once it is ready. */
export function useAssetFont(tenantId: string, projectId: string, assetId: string | null): string | null | false {
  const family = assetId ? fontFamily(assetId) : null;
  const [ready, setReady] = useState<boolean | null>(null);
  useEffect(() => {
    if (!assetId || !family) { setReady(null); return; }
    let pending = loadedFonts.get(family);
    if (!pending) {
      pending = api.getNarrativeFont(tenantId, projectId, assetId)
        .then(buffer => new FontFace(family, buffer).load())
        .then(face => { document.fonts.add(face); return true; })
        .catch(() => { loadedFonts.delete(family); return false; });
      loadedFonts.set(family, pending);
    }
    let live = true;
    setReady(null);
    void pending.then(ok => { if (live) setReady(ok); });
    return () => { live = false; };
  }, [tenantId, projectId, assetId, family]);
  return ready === false ? false : ready && family ? family : null;
}
