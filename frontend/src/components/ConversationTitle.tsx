import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Conversation } from "../lib/types";
import { Button } from "./ui";

export function ConversationTitle({ tenantId, conversation, disabled, onRenamed, onAccessDenied }: {
  tenantId: string; conversation: Conversation; disabled: boolean;
  onRenamed: (conversation: Conversation) => void; onAccessDenied: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conversation.title);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef(false);
  useEffect(() => () => request.current?.abort(), [tenantId, conversation.id]);
  useEffect(() => {
    if (!editing && restoreFocus.current) {
      trigger.current?.focus({ preventScroll: true });
      restoreFocus.current = false;
    }
  }, [editing]);
  function finishEditing() {
    restoreFocus.current = true;
    setEditing(false);
  }
  async function save() {
    if (!title.trim() || disabled || saving) return;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setSaving(true); setError(null);
    try {
      const renamed = await api.renameConversation(tenantId, conversation.id, title.trim(), controller.signal);
      if (controller.signal.aborted) return;
      onRenamed(renamed); finishEditing();
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "The title could not be saved. Retry or refresh the conversation.");
      if (err instanceof ApiError && [401, 403].includes(err.status)) onAccessDenied();
    } finally { if (!controller.signal.aborted) setSaving(false); }
  }
  if (!editing) return <button ref={trigger} disabled={disabled} onClick={() => { setTitle(conversation.title); setEditing(true); }}
    className="rounded px-2 py-1 text-xs text-brand-700 underline underline-offset-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-brand-500">Rename</button>;
  return <form onSubmit={(event) => { event.preventDefault(); void save(); }} className="mt-3 space-y-2">
    <label className="block text-xs text-slate-600">Conversation title
      <input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus maxLength={200} disabled={saving || disabled}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-2 focus:outline-brand-500" />
    </label>
    <div className="flex gap-2"><Button type="submit" disabled={saving || disabled || !title.trim()}>Save title</Button>
      <Button type="button" variant="ghost" disabled={saving} onClick={finishEditing}>Cancel rename</Button></div>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
  </form>;
}
