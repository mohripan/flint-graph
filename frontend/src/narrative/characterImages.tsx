import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import type { CharacterProfile } from "../lib/api";

// Image bytes never change for an asset ID, so each (asset, variant) is fetched once
// with the creator's credentials and reused as an object URL.
const urls = new Map<string, Promise<string>>();

export function useNarrativeImage(tenantId: string, projectId: string, assetId: string | null,
  variant: "image" | "thumbnail"): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!assetId) { setUrl(null); return; }
    const key = `${tenantId}:${projectId}:${assetId}:${variant}`;
    let pending = urls.get(key);
    if (!pending) {
      pending = api.getNarrativeImage(tenantId, projectId, assetId, variant).then(blob => URL.createObjectURL(blob));
      urls.set(key, pending);
      pending.catch(() => urls.delete(key));
    }
    let live = true;
    pending.then(value => { if (live) setUrl(value); }, () => { if (live) setUrl(null); });
    return () => { live = false; };
  }, [tenantId, projectId, assetId, variant]);
  return url;
}

export interface CharacterProfiles {
  tenantId: string; projectId: string; profiles: Record<string, CharacterProfile>;
  put: (profile: CharacterProfile) => void; reload: () => Promise<void>;
}
export const CharacterProfilesContext = createContext<CharacterProfiles | null>(null);

// Profiles are editor metadata for the open project; loading failures leave names only.
export function CharacterProfilesProvider({ tenantId, projectId, children }: {
  tenantId: string; projectId: string; children: ReactNode;
}) {
  const [profiles, setProfiles] = useState<Record<string, CharacterProfile>>({});
  const reload = useCallback(async () => {
    if (!projectId) return;
    try {
      const listed = await api.listCharacterProfiles(tenantId, projectId);
      if (listed.project_id !== projectId) return;
      setProfiles(Object.fromEntries(listed.profiles.map(profile => [profile.character_id, profile])));
    } catch { /* Characters still work by name; the sheet reports its own errors. */ }
  }, [tenantId, projectId]);
  useEffect(() => { setProfiles({}); void reload(); }, [reload]);
  const put = useCallback((profile: CharacterProfile) => setProfiles(current => {
    const known = current[profile.character_id];
    return known && known.version > profile.version ? current : { ...current, [profile.character_id]: profile };
  }), []);
  const value = useMemo(() => ({ tenantId, projectId, profiles, put, reload }),
    [tenantId, projectId, profiles, put, reload]);
  return <CharacterProfilesContext.Provider value={value}>{children}</CharacterProfilesContext.Provider>;
}

export function CharacterAvatar({ characterId, name, size = 32 }: { characterId: string; name: string; size?: number }) {
  const context = useContext(CharacterProfilesContext);
  const assetId = context?.profiles[characterId]?.portrait?.id ?? null;
  const url = useNarrativeImage(context?.tenantId ?? "", context?.projectId ?? "", context ? assetId : null, "thumbnail");
  const initial = (name.trim()[0] ?? characterId[0] ?? "?").toUpperCase();
  return <span className="studio-avatar" style={{ width: size, height: size }} aria-hidden="true">
    {url ? <img src={url} alt="" /> : initial}
  </span>;
}
