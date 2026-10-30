import { checkCondition, defaultCondition, own } from "./model";
import { Field, ScalarInput, VariableSelect } from "./FormFields";
import type { Condition, StoryDraft } from "./types";

const comparisons = [ ["eq", "Equals"], ["ne", "Does not equal"], ["lt", "Less than"],
  ["le", "At most"], ["gt", "Greater than"], ["ge", "At least"] ] as const;

export function ConditionEditor({ story, value, onChange, onError, label = "Condition" }: {
  story: StoryDraft; value: Condition; onChange: (next: Condition) => void;
  onError: (message: string) => void; label?: string;
}) {
  const accept = (next: Condition) => {
    try { onChange(checkCondition(next)); }
    catch (error) { onError(error instanceof Error ? error.message : "Could not change the condition."); }
  };
  return <Tree story={story} value={value} onChange={accept} label={label} />;
}

function Tree({ story, value, onChange, label }: {
  story: StoryDraft; value: Condition; onChange: (next: Condition) => void; label: string;
}) {
  function operator(op: Condition["op"]) {
    if (op === "all" || op === "any") {
      onChange({ op, children: value.op === "all" || value.op === "any" ? value.children : [value] });
    } else if (op === "not") {
      onChange(value.op === "not" ? value : { op, child: value });
    } else {
      const leaf = "variable" in value ? value : defaultCondition(story);
      onChange({ ...leaf, op } as Condition);
    }
  }
  const declaration = "variable" in value ? own(story.variables, value.variable) : undefined;
  return <fieldset className="studio-condition"><legend>{label}</legend>
    <Field label={`${label} operator`}><select value={value.op}
      onChange={event => operator(event.target.value as Condition["op"])}>
      {comparisons.filter(([op]) => !declaration || declaration.type === "int" || op === "eq" || op === "ne")
        .map(([op, name]) => <option value={op} key={op}>{name}</option>)}
      <option value="all">All checks</option><option value="any">Any check</option><option value="not">Not</option>
    </select></Field>
    {value.op === "all" || value.op === "any" ? <>
      {value.children.map((child, index) => <div className="studio-condition-child" key={index}>
        <Tree story={story} value={child} label={`${label} · check ${index + 1}`}
          onChange={next => onChange({ ...value, children: value.children.map((item, at) => at === index ? next : item) })} />
        <button type="button" className="studio-link" disabled={value.children.length === 1}
          onClick={() => onChange({ ...value, children: value.children.filter((_, at) => at !== index) })}>Remove check {index + 1}</button>
      </div>)}
      <button type="button" className="studio-secondary" onClick={() => onChange({ ...value,
        children: [...value.children, defaultCondition(story)] })}>Add check</button>
    </> : value.op === "not" ? <Tree story={story} value={value.child} label={`${label} · inverted check`}
      onChange={child => onChange({ ...value, child })} /> : "variable" in value ? <>
      <VariableSelect story={story} value={value.variable} onChange={variable => {
        const next = own(story.variables, variable);
        onChange({ op: next?.type === "int" ? value.op : "eq", variable,
          value: next?.initial ?? "" } as Condition);
      }} />
      <ScalarInput declaration={declaration} value={value.value}
        onChange={next => onChange({ ...value, value: next })} />
    </> : null}
  </fieldset>;
}
