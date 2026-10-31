import { useContext, useRef, useState } from "react";
import { ApiError, api } from "../lib/api";
import { proposalActions } from "./assistantModel";
import { CharacterProfilesContext } from "./characterImages";
import type { AssistantAction, AssistantProposal, StoryDraft } from "./types";

const message = (error: unknown) => error instanceof Error && error.message ? error.message : "Could not start generating.";

// Image jobs the assistant suggested. Each starts only when the creator clicks it,
// with their own access, and shows up in Characters or Assets for approval.
export function ProposalActions({ proposal, story, tenantId, projectId, canWrite }: {
  proposal: AssistantProposal; story: StoryDraft | null; tenantId: string; projectId: string; canWrite: boolean;
}) {
  const profiles = useContext(CharacterProfilesContext);
  const keys = useRef(new Map<number, string>());
  const [state, setState] = useState<Record<number, { busy?: boolean; done?: string; error?: string }>>({});
  const actions = proposalActions(story, proposal.operations);
  if (!actions.length || proposal.status === "rejected") return null;

  async function start(index: number, action: AssistantAction) {
    const key = keys.current.get(index) ?? crypto.randomUUID();
    keys.current.set(index, key);
    setState(current => ({ ...current, [index]: { busy: true } }));
    try {
      if (action.op === "generate_backgrounds") {
        await api.createBackgroundJob(tenantId, projectId, action.description, 4);
        setState(current => ({ ...current, [index]: { done: "Started. The backgrounds appear in Assets for approval." } }));
        return;
      }
      // Keep the character's described looks with them, as the character sheet would.
      const save = (version: number) => api.saveCharacterProfile(tenantId, projectId, action.character, {
        base_version: version, appearance: action.appearance, character_type: action.character_type, framing: action.framing });
      let profile;
      try { profile = await save(profiles?.profiles[action.character]?.version ?? 0); }
      catch (error) {
        if (!(error instanceof ApiError && error.status === 409) || !profiles) throw error;
        await profiles.reload();
        const listed = await api.listCharacterProfiles(tenantId, projectId);
        profile = await save(listed.profiles.find(item => item.character_id === action.character)?.version ?? 0);
      }
      profiles?.put(profile);
      await api.createPortraitJob(tenantId, projectId, action.character, {
        appearance: action.appearance, character_type: action.character_type, framing: action.framing,
        count: 4, idempotency_key: key, transparent: action.transparent,
      });
      setState(current => ({ ...current, [index]: { done: `Started. Approve the ${action.transparent ? "sprites" : "portraits"} in Characters when they are ready.` } }));
    } catch (error) {
      setState(current => ({ ...current, [index]: { error: message(error) } }));
    }
  }

  return <div className="assistant-actions" aria-label="Suggested image generation">
    <strong>Suggested pictures</strong>
    <ul>{actions.map(({ action, label, ready }, index) => {
      const status = state[index];
      return <li key={index}>
        <span>{label}</span>
        {status?.done ? <small className="studio-hint" role="status">{status.done}</small>
          : canWrite && <button type="button" className="studio-secondary" disabled={!ready || status?.busy}
            onClick={() => void start(index, action)}>{status?.busy ? "Starting…" : "Generate"}</button>}
        {!ready && !status?.done && <small className="studio-hint">Accept the proposal first so the character exists.</small>}
        {status?.error && <small className="studio-error" role="alert">{status.error}</small>}
      </li>;
    })}</ul>
  </div>;
}
