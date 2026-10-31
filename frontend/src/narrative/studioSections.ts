// The Studio's sections. On wide screens they sit in the app sidebar under Studio,
// in groups; phones keep the tab row above the desk.
export type Panel = "write" | "scenes" | "map" | "characters" | "assets" | "look" | "state" | "story" | "history" | "source";
export type Section = "assistant" | Panel;
export const PANELS: Array<[Panel, string]> = [["write", "Write"], ["scenes", "Scenes"], ["map", "Map"],
  ["characters", "Characters"], ["assets", "Assets"], ["look", "Look"], ["state", "State"], ["story", "Details"],
  ["history", "History"], ["source", "Source"]];
// Scenes is the Write rail on wide screens, so the sidebar leaves it out.
export const SECTION_GROUPS: Array<{ label: string; panels: Panel[] }> = [
  { label: "Writing", panels: ["write", "map"] },
  { label: "Cast & art", panels: ["characters", "assets", "look"] },
  { label: "Story setup", panels: ["state", "story"] },
  { label: "Advanced", panels: ["history", "source"] },
];
export function panelLabel(panel: Panel): string {
  return PANELS.find(([id]) => id === panel)?.[1] ?? panel;
}
/** The sidebar entry shown as current. */
export function currentSection(assistant: boolean, panel: Panel): Section {
  return assistant ? "assistant" : panel === "scenes" ? "write" : panel;
}
