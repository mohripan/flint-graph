import { useEffect, useState } from "react";
import { api } from "../lib/api";

const urls = new Map<string, Promise<string>>();

/** A picture attached to a message, fetched with the person's own credentials. */
export function AssistantPicture({ tenantId, projectId, imageId, small = false }: {
  tenantId: string; projectId: string; imageId: string; small?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const key = `${tenantId}:${projectId}:${imageId}`;
    let pending = urls.get(key);
    if (!pending) {
      pending = api.getAssistantImage(tenantId, projectId, imageId).then(blob => URL.createObjectURL(blob));
      urls.set(key, pending);
      pending.catch(() => urls.delete(key));
    }
    let live = true;
    pending.then(value => { if (live) setUrl(value); }, () => { if (live) setUrl(null); });
    return () => { live = false; };
  }, [tenantId, projectId, imageId]);
  if (!url) return <span className="assistant-picture-empty" role="img" aria-label="Your picture" />;
  const picture = <img src={url} alt="Your screenshot" />;
  return small ? <span className="assistant-picture is-small">{picture}</span>
    : <a className="assistant-picture" href={url} target="_blank" rel="noreferrer" title="Open the full picture">{picture}</a>;
}
