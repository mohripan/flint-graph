import { Field, ScalarInput, TargetSelect } from "./FormFields";
import { addCharacter, addVariable, deleteCharacter, deleteVariable } from "./model";
import type { StoryDraft } from "./types";

interface Props {
  story: StoryDraft; readOnly: boolean;
  onChange: (story: StoryDraft, group?: string) => void; onError: (message: string) => void;
}

export function CharactersPanel({ story, readOnly, onChange, onError }: Props) {
  return <fieldset disabled={readOnly} className="studio-form">
    <div className="studio-section-heading"><h2>Characters</h2>
      <button type="button" className="studio-secondary" onClick={() => {
        try { onChange(addCharacter(story).story); }
        catch (error) { onError(error instanceof Error ? error.message : "Could not add a character."); }
      }}>Add character</button></div>
    <p className="studio-hint">Choose these speakers when writing dialogue. Their IDs stay stable across scene edits.</p>
    {!Object.keys(story.characters).length && <p className="studio-empty">No characters yet. Narration works without one.</p>}
    {Object.entries(story.characters).map(([id, character]) => <section className="studio-option" key={id}>
      <div className="studio-section-heading"><h3>{character.name || "Unnamed character"}</h3><code>{id}</code></div>
      <Field label={`Character name · ${id}`}><input value={character.name} onChange={event => onChange({
        ...story, characters: { ...story.characters, [id]: { ...character, name: event.target.value } },
      }, `character:${id}:name`)} /></Field>
      <button type="button" className="studio-link studio-danger" onClick={() => {
        try { onChange(deleteCharacter(story, id)); }
        catch (error) { onError(error instanceof Error ? error.message : "Could not remove a character."); }
      }}>Remove character</button>
    </section>)}
  </fieldset>;
}

export function StatePanel({ story, readOnly, onChange, onError }: Props) {
  return <fieldset disabled={readOnly} className="studio-form">
    <h2>Story state</h2>
    <p className="studio-hint">Track what happened, then use these variables in choices and conditions.</p>
    <div className="studio-actions">{(["bool", "int", "enum"] as const).map(type =>
      <button type="button" className="studio-secondary" key={type} onClick={() => {
        try { onChange(addVariable(story, type).story); }
        catch (error) { onError(error instanceof Error ? error.message : "Could not add state."); }
      }}>{type === "bool" ? "Add true/false" : type === "int" ? "Add integer" : "Add enum"}</button>)}</div>
    {Object.entries(story.variables).map(([id, declaration]) => <section className="studio-option" key={id}>
      <div className="studio-section-heading"><h3>{id}</h3><span className="studio-kind">{declaration.type}</span></div>
      {declaration.type === "enum" && <Field label={`Allowed values · ${id}`} hint="One unique, nonempty value per line.">
        <textarea rows={4} value={(declaration.values ?? []).join("\n")} onChange={event => onChange({
          ...story, variables: { ...story.variables, [id]: { ...declaration, values: event.target.value.split("\n") } },
        }, `variable:${id}:values`)} />
      </Field>}
      <ScalarInput declaration={declaration} value={declaration.initial} label={`Initial value · ${id}`}
        onChange={initial => onChange({ ...story, variables: { ...story.variables,
          [id]: { ...declaration, initial } } }, `variable:${id}:initial`)} />
      <button type="button" className="studio-link studio-danger" onClick={() => {
        try { onChange(deleteVariable(story, id)); }
        catch (error) { onError(error instanceof Error ? error.message : "Could not remove state."); }
      }}>Remove variable</button>
    </section>)}
    {!Object.keys(story.variables).length && <p className="studio-empty">A linear story needs no state. Add a flag or number when paths depend on earlier choices.</p>}
  </fieldset>;
}

export function StoryPanel({ story, readOnly, onChange }: Props) {
  return <fieldset disabled={readOnly} className="studio-form"><h2>Story details</h2>
    <Field label="Story title"><input value={story.title}
      onChange={event => onChange({ ...story, title: event.target.value }, "story:title")} /></Field>
    <Field label="Language" hint="Language tag, such as en, ja or en-GB."><input value={story.language}
      onChange={event => onChange({ ...story, language: event.target.value }, "story:language")} /></Field>
    <TargetSelect story={story} value={story.entry} label="Start the game at"
      onChange={entry => onChange({ ...story, entry })} />
    <p className="studio-hint">Project name organizes your workspace. This title appears inside the game.</p>
  </fieldset>;
}
