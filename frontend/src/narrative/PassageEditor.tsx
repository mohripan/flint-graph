import { useEffect, useRef } from "react";
import { CharacterAvatar } from "./characterImages";
import { TargetSelect } from "./FormFields";
import { deletePassage, describeStage, insertLineAfter, removeLine, replaceScene } from "./model";
import type { Passage } from "./passages";
import { SceneForm } from "./SceneForm";
import { SceneStage, UpgradeNotice } from "./StageEditor";
import { setLineExpression, setLineSpeaker } from "./stageModel";
import type { StageSnapshot } from "./stageModel";
import type { StoryDraft } from "./types";

// One scene as a script: every line in order, with state changes inline and the
// choice, condition or ending that closes it. Edits change the same story nodes
// the runtime plays; nothing here is a separate format. In story format 2 a stage
// step opening the scene is edited in the panel above the lines.
export function PassageEditor({ story, passage, readOnly, onChange, onError, onOpenNode, onDeleted, inherited, onUpgrade }: {
  story: StoryDraft; passage: Passage; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
  onOpenNode: (id: string) => void; onDeleted: (next: StoryDraft) => void;
  inherited?: StageSnapshot; onUpgrade?: () => void;
}) {
  const focusNext = useRef<string | null>(null), list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!focusNext.current) return;
    list.current?.querySelector<HTMLTextAreaElement>(`[data-line="${CSS.escape(focusNext.current)}"]`)?.focus();
    focusNext.current = null;
  });
  const staged = story.schema_version === "2";
  const opening = staged && story.nodes[passage.id]?.type === "stage" && passage.nodes.length > 1;
  const body = (passage.exit ? passage.nodes.slice(0, -1) : passage.nodes).slice(opening ? 1 : 0);
  const last = story.nodes[passage.nodes[passage.nodes.length - 1]];
  const run = (action: () => void) => { try { action(); } catch (error) { onError(error instanceof Error ? error.message : String(error)); } };
  const characters = Object.entries(story.characters);
  return <div className="studio-script">
    <div className="studio-section-heading"><div><p className="studio-eyebrow">Scene</p>
      <h2 className="studio-script-title">{passage.title}</h2></div>
      <code>{passage.id}{story.entry === passage.id ? " · start" : ""}</code></div>
    {staged ? <SceneStage story={story} head={passage.id} inherited={inherited} readOnly={readOnly}
      onChange={onChange} onError={onError} />
      : onUpgrade && <UpgradeNotice readOnly={readOnly} onUpgrade={onUpgrade} />}
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
        if (node.type === "stage") return <li key={id} className="studio-script-state">
          <span aria-hidden="true">▣</span>
          <span>{describeStage(story, node)}</span>
          {!readOnly && <button type="button" className="studio-link studio-danger"
            onClick={() => run(() => onChange(removeLine(story, id)))}>Remove</button>}
        </li>;
        if (node.type !== "line") return null;
        return <li key={id} className="studio-script-line">
          <div className="studio-script-who">
            {node.speaker && story.characters[node.speaker] &&
              <CharacterAvatar characterId={node.speaker} name={story.characters[node.speaker].name} />}
            <select aria-label="Speaker" className="studio-script-speaker" disabled={readOnly} value={node.speaker ?? ""}
              onChange={event => run(() => onChange(setLineSpeaker(story, id, event.target.value || null), `${id}:speaker`))}>
              <option value="">Narration</option>
              {characters.map(([key, character]) => <option key={key} value={key}>{character.name}</option>)}
            </select>
            {staged && node.speaker && Object.keys(story.characters[node.speaker]?.sprites ?? {}).length > 0 &&
              <select aria-label="Expression" className="studio-script-expression" disabled={readOnly} value={node.expression ?? ""}
                onChange={event => run(() => onChange(setLineExpression(story, id, event.target.value || null), `${id}:expression`))}>
                <option value="">Same expression</option>
                {Object.keys(story.characters[node.speaker]?.sprites ?? {}).map(sprite =>
                  <option key={sprite} value={sprite}>{sprite}</option>)}
              </select>}
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
        : last && (last.type === "line" || last.type === "set" || last.type === "stage") ? <fieldset className="studio-form" disabled={readOnly}>
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
