import type { ReactNode } from "react";
import { own } from "./model";
import type { Scalar, StoryDraft, VariableDeclaration } from "./types";

export function Field({ label, children, hint }: {
  label: string; children: ReactNode; hint?: string;
}) {
  return <label className="studio-field"><span>{label}</span>{children}
    {hint && <small>{hint}</small>}</label>;
}

export function ScalarInput({ declaration, value, onChange, label = "Value" }: {
  declaration?: VariableDeclaration; value: Scalar; onChange: (value: Scalar) => void; label?: string;
}) {
  if (declaration?.type === "bool") return <Field label={label}>
    <select value={typeof value === "boolean" ? String(value) : ""}
      onChange={event => onChange(event.target.value === "true")}>
      <option value="" disabled>Choose true or false</option>
      <option value="true">True</option><option value="false">False</option>
    </select></Field>;
  if (declaration?.type === "enum") return <Field label={label}>
    <select value={typeof value === "string" && declaration.values?.includes(value) ? value : ""}
      onChange={event => onChange(event.target.value)}>
      <option value="" disabled>Choose a listed value</option>
      {(declaration.values ?? []).map((item, index) => <option value={item} key={`${index}:${item}`}>{item}</option>)}
    </select></Field>;
  return <Field label={label} hint="Whole number from −2,147,483,648 to 2,147,483,647.">
    <input inputMode="numeric" value={value === null ? "" : String(value)}
      onChange={event => {
        const raw = event.target.value;
        const number = /^-?\d+$/.test(raw) ? Number(raw) : Number.NaN;
        onChange(Number.isSafeInteger(number) ? number : raw);
      }} /></Field>;
}

export function VariableSelect({ story, value, onChange, label = "Variable", integersOnly = false }: {
  story: StoryDraft; value: string; onChange: (value: string) => void;
  label?: string; integersOnly?: boolean;
}) {
  const entries = Object.entries(story.variables).filter(([, item]) => !integersOnly || item.type === "int");
  return <Field label={label}><select value={value} onChange={event => onChange(event.target.value)}>
    {!entries.some(([id]) => id === value) && <option value={value}>Unavailable variable: {value}</option>}
    {!entries.length && <option value="">Add a variable first</option>}
    {entries.map(([id, item]) => <option key={id} value={id}>{id} · {item.type}</option>)}
  </select></Field>;
}

export function TargetSelect({ story, value, onChange, label }: {
  story: StoryDraft; value: string; onChange: (value: string) => void; label: string;
}) {
  return <Field label={label}><select value={value} onChange={event => onChange(event.target.value)}>
    {!own(story.nodes, value) && <option value={value}>Missing scene: {value || "none"}</option>}
    {Object.entries(story.nodes).map(([id, node]) => <option key={id} value={id}>
      {id} · {"text" in node ? node.text.slice(0, 48) : node.type}
    </option>)}
  </select></Field>;
}
