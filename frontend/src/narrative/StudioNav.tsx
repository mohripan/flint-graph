import { createContext } from "react";
import { SECTION_GROUPS, panelLabel } from "./studioSections";
import type { Panel, Section } from "./studioSections";

// The app sidebar's place for the open project's sections; the Studio renders into it.
export const StudioNavSlot = createContext<HTMLElement | null>(null);

const item = (selected: boolean) => `flex w-full items-center rounded-lg px-3 py-1.5 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
  selected ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`;

export function StudioSideNav({ projectName, current, assistantReady, onProjects, onAssistant, onPanel }: {
  projectName: string; current: Section; assistantReady: boolean;
  onProjects: () => void; onAssistant: () => void; onPanel: (panel: Panel) => void;
}) {
  return <nav aria-label="Studio sections" className="mt-1 mb-2 ml-3 border-l border-slate-200 pl-2">
    <button type="button" onClick={onProjects} className="w-full truncate px-3 py-1 text-left text-xs text-slate-500 hover:text-slate-700"
      title="Back to all projects">← {projectName}</button>
    <ul className="space-y-0.5">
      <li><button type="button" className={item(current === "assistant")} aria-current={current === "assistant" ? "page" : undefined}
        disabled={!assistantReady} onClick={onAssistant}>Assistant</button></li>
      {SECTION_GROUPS.map(group => <li key={group.label}>
        <p className="mt-3 mb-1 px-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{group.label}</p>
        <ul className="space-y-0.5">{group.panels.map(panel => <li key={panel}>
          <button type="button" className={item(current === panel)} aria-current={current === panel ? "page" : undefined}
            onClick={() => onPanel(panel)}>{panelLabel(panel)}</button></li>)}</ul>
      </li>)}
    </ul>
  </nav>;
}
