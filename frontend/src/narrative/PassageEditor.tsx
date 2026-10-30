import { useEffect, useRef } from "react";
import { CharacterAvatar } from "./characterImages";
import { TargetSelect } from "./FormFields";
import { deletePassage, insertLineAfter, removeLine, replaceScene } from "./model";
import type { Passage } from "./passages";
import { SceneForm } from "./SceneForm";
import type { StoryDraft } from "./types";

// One scene as a script: every line in order, with state changes inline and the
// choice, condition or ending that closes it. Edits change the same story nodes
// the runtime plays; nothing here is a separate format.
export function PassageEditor({ story, passage, readOnly, onChange, onError, onOpenNode, onDeleted }: {
  story: StoryDraft; passage: Passage; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
  onOpenNode: (id: string) => void; onDeleted: (next: StoryDraft) => void;
}) {
  const focusNext = useRef<string | null>(null), list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!focusNext.current) return;
    list.current?.querySelector<HTMLTextAreaElement>(`[data-line="${CSS.escape(focusNext.current)}"]`)?.focus();
    focusNext.current = null;
  });
  const body = passage.exit ? passage.nodes.slice(0, -1) : passage.nodes;
  const last = story.nodes[passage.nodes[passage.nodes.length - 1]];
  const run = (action: () => void) => { try { action(); } catch (error) { onError(error instanceof Error ? error.message : String(error)); } };
  const characters = Object.entries(story.characters);
  return <div className="studio-script">
    <div className="studio-section-heading"><div><p className="studio-eyebrow">Scene</p>
      <h2 className="studio-script-title">{passage.title}</h2></div>
      <code>{passage.id}{story.entry === passage.id ? " · start" : ""}</code></div>
    <ol ref={list} className="studio-script-lines">
      {body.map(id => {
        const node = story.nodes[id];
        if (!node) return null;
        if (node.type === "set") return <li key={id} className="studio-script-state">
          <span aria-hidden="true">⚙</span>
          <span>{node.operations.map(item => `${item.variable} ${item.op === "set" ? "=" : "+"} ${String(item.value)}`).join(", ")}</span>
          <button type="button" className="studio-link" onClick={() => onOpenNode(id)}>Edit</button>
          {!readOnly && <button type="button" className="studio-link studio-danger"
            onClick={() => run(() => onChange(removeLine(story, id)))}>Remove</button>}
        </li>;
        if (node.type !== "line") return null;
        return <li key={id} className="studio-script-line">
          <div className="studio-script-who">
            {node.speaker && story.characters[node.speaker] &&
              <CharacterAvatar characterId={node.speaker} name={story.characters[node.speaker].name} />}
            <select aria-label="Speaker" className="studio-script-speaker" disabled={readOnly} value={node.speaker ?? ""}
              onChange={event => {
                const { speaker: _, ...rest } = node;
                onChange(replaceScene(story, id, event.target.value ? { ...rest, speaker: event.target.value } : rest), `${id}:speaker`);
              }}>
              <option value="">Narration</option>
              {characters.map(([key, character]) => <option key={key} value={key}>{character.name}</option>)}
            </select>
          </div>
          <textarea data-line={id} aria-label="Line" className="studio-script-text studio-prose" readOnly={readOnly}
            rows={Math.min(8, Math.max(1, Math.ceil(node.text.length / 70)))} value={node.text}
            onChange={event => onChange(replaceScene(story, id, { ...node, text: event.target.value }), `${id}:text`)}
            onKeyDown={event => {
              if (readOnly || !(event.ctrlKey || event.metaKey) || event.key !== "Enter") return;
              event.preventDefault();
              run(() => { const added = insertLineAfter(story, id); focusNext.current = added.id; onChange(added.story); });
            }} />
          {!readOnly && <div className="studio-script-actions">
            <button type="button" className="studio-link" onClick={() => run(() => {
              const added = insertLineAfter(story, id); focusNext.current = added.id; onChange(added.story);
            })}>Add line below</button>
            <button type="button" className="studio-link studio-danger" onClick={() => run(() => onChange(removeLine(story, id)))}>Remove</button>
          </div>}
        </li>;
      })}
    </ol>
    {!readOnly && body.length > 0 && <p className="studio-hint">Ctrl/⌘ + Enter adds the next line.</p>}
    <section className="studio-script-exit" aria-label="How this scene ends">
      <h3>Then</h3>
      {passage.exit ? <SceneForm story={story} sceneId={passage.exit} readOnly={readOnly} onChange={onChange} onError={onError} />
        : last && (last.type === "line" || last.type === "set") ? <fieldset className="studio-form" disabled={readOnly}>
          <TargetSelect story={story} value={last.next} label="Continue to scene"
            onChange={target => onChange(replaceScene(story, passage.nodes[passage.nodes.length - 1], { ...last, next: target }))} />
        </fieldset> : null}
    </section>
    {!readOnly && <div className="studio-scene-actions">
      <button type="button" className="studio-link studio-danger" onClick={() => run(() => {
        if (!window.confirm(`Delete the scene "${passage.title}" and its ${passage.nodes.length} steps?`)) return;
        onDeleted(deletePassage(story, passage.nodes));
      })}>Delete scene</button></div>}
  </div>;
}
