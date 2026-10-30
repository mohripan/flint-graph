import { ConditionEditor } from "./ConditionEditor";
import { Field, ScalarInput, TargetSelect, VariableSelect } from "./FormFields";
import { addChoiceOption, defaultCondition, getScene, own, replaceScene } from "./model";
import type { StoryDraft, StoryNode } from "./types";

export function SceneForm({ story, sceneId, onChange, onError, readOnly }: {
  story: StoryDraft; sceneId: string; onChange: (story: StoryDraft, group?: string) => void;
  onError: (message: string) => void; readOnly: boolean;
}) {
  const node = getScene(story, sceneId);
  if (!node) return <p className="studio-empty">Choose a scene from the list.</p>;
  const update = (next: StoryNode, field?: string) => onChange(replaceScene(story, sceneId, next),
    field ? `${sceneId}:${field}` : undefined);
  return <fieldset disabled={readOnly} className="studio-form">
    <div className="studio-section-heading"><h2>{node.type === "line" ? "Write the scene" :
      node.type === "choice" ? "Give the player a choice" : node.type === "end" ? "Write the ending" :
      node.type === "set" ? "Change story state" : "Route by a condition"}</h2>
      <code>{sceneId}</code></div>
    {node.type === "line" && <>
      <Field label="Speaker"><select value={node.speaker ?? ""} onChange={event => {
        const next = { ...node };
        if (event.target.value) next.speaker = event.target.value; else delete next.speaker;
        update(next);
      }}><option value="">Narration</option>
        {Object.entries(story.characters).map(([id, character]) =>
          <option key={id} value={id}>{character.name} · {id}</option>)}
      </select></Field>
      <Field label="Scene text"><textarea className="studio-prose" rows={9} value={node.text}
        onChange={event => update({ ...node, text: event.target.value }, "text")} /></Field>
      <TargetSelect story={story} value={node.next} label="Next scene"
        onChange={next => update({ ...node, next })} />
    </>}
    {node.type === "end" && <>
      <Field label="Ending text"><textarea className="studio-prose" rows={7} value={node.text}
        onChange={event => update({ ...node, text: event.target.value }, "text")} /></Field>
      <Field label="Ending key" hint="A stable lowercase identifier for this ending.">
        <input value={node.ending} onChange={event => update({ ...node, ending: event.target.value }, "ending")} />
      </Field>
    </>}
    {node.type === "choice" && <>
      <Field label="Choice prompt"><textarea className="studio-prose" rows={4} value={node.text}
        onChange={event => update({ ...node, text: event.target.value }, "text")} /></Field>
      <div className="studio-options">{node.options.map((option, index) => {
        const change = (next: typeof option, field?: string) => update({ ...node,
          options: node.options.map((item, at) => at === index ? next : item) }, field);
        return <section className="studio-option" key={option.id}>
          <div className="studio-section-heading"><h3>Option {index + 1}</h3><code>{option.id}</code></div>
          <Field label={`Option ${index + 1} text`}><textarea rows={2} value={option.text}
            onChange={event => change({ ...option, text: event.target.value }, `option:${option.id}`)} /></Field>
          <TargetSelect story={story} value={option.target} label={`Option ${index + 1} leads to`}
            onChange={target => change({ ...option, target })} />
          <label className="studio-check"><input type="checkbox" checked={Boolean(option.condition)}
            disabled={!Object.keys(story.variables).length && !option.condition}
            onChange={event => {
              const next = { ...option };
              if (event.target.checked) next.condition = defaultCondition(story);
              else delete next.condition;
              change(next);
            }} />Only show option {index + 1} when a condition matches</label>
          {option.condition && <ConditionEditor story={story} value={option.condition}
            label={`Option ${index + 1} condition`} onError={onError}
            onChange={condition => change({ ...option, condition })} />}
          <button type="button" className="studio-link studio-danger" disabled={node.options.length <= 1}
            onClick={() => update({ ...node, options: node.options.filter((_, at) => at !== index) })}>
            Remove option {index + 1}</button>
        </section>;
      })}</div>
      {!Object.keys(story.variables).length && <p className="studio-hint">Add a variable in State to make choices conditional.</p>}
      <button type="button" className="studio-secondary" disabled={node.options.length >= 32}
        onClick={() => onChange(addChoiceOption(story, sceneId))}>Add option</button>
    </>}
    {node.type === "set" && <>
      <p className="studio-hint">These changes happen before the next scene appears.</p>
      {node.operations.map((operation, index) => {
        const change = (next: typeof operation) => update({ ...node,
          operations: node.operations.map((item, at) => at === index ? next : item) });
        return <section className="studio-option" key={index}>
          <h3>Change {index + 1}</h3>
          <Field label={`Change ${index + 1} operation`}><select value={operation.op} onChange={event => {
            if (event.target.value === "increment") {
              const id = own(story.variables, operation.variable)?.type === "int" ? operation.variable :
                Object.entries(story.variables).find(([, declaration]) => declaration.type === "int")?.[0];
              if (!id) { onError("Add an integer variable before choosing increment."); return; }
              change({ op: "increment", variable: id, value: 1 });
            } else change({ ...operation, op: "set" });
          }}><option value="set">Set a value</option><option value="increment">Increment a number</option></select></Field>
          <VariableSelect story={story} value={operation.variable} integersOnly={operation.op === "increment"}
            label={`Change ${index + 1} variable`} onChange={variable => change({ ...operation, variable,
              value: operation.op === "increment" ? 1 : own(story.variables, variable)?.initial ?? "" })} />
          <ScalarInput declaration={own(story.variables, operation.variable)} value={operation.value}
            label={`Change ${index + 1} value`} onChange={value => change({ ...operation, value })} />
          <button type="button" className="studio-link studio-danger" disabled={node.operations.length <= 1}
            onClick={() => update({ ...node, operations: node.operations.filter((_, at) => at !== index) })}>
            Remove change {index + 1}</button>
        </section>;
      })}
      <button type="button" className="studio-secondary" disabled={node.operations.length >= 256}
        onClick={() => {
          const variable = Object.keys(story.variables)[0];
          if (!variable) { onError("Add a variable first."); return; }
          update({ ...node, operations: [...node.operations, { op: "set", variable,
            value: story.variables[variable].initial }] });
        }}>Add state change</button>
      <TargetSelect story={story} value={node.next} label="After these changes"
        onChange={next => update({ ...node, next })} />
    </>}
    {node.type === "branch" && <>
      <ConditionEditor story={story} value={node.condition} onError={onError}
        onChange={condition => update({ ...node, condition })} />
      <TargetSelect story={story} value={node.if_true} label="When the condition matches"
        onChange={if_true => update({ ...node, if_true })} />
      <TargetSelect story={story} value={node.if_false} label="Otherwise"
        onChange={if_false => update({ ...node, if_false })} />
    </>}
  </fieldset>;
}
