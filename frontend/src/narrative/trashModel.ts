// What deleting a project forever takes with it, in words a creator can weigh (ADR 0073).

export interface ProjectContents {
  revisions: number; files: number; characters: number; conversations: number; releases: number;
  /** Work still running, e.g. "2 picture jobs". Nothing can be deleted until it has finished. */
  working: string[];
}

const counted = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/** One line per kind of thing that would be lost, leaving out what the project does not have. */
export function deletionList(contents: ProjectContents): string[] {
  return [
    contents.revisions > 0 && `The story and its ${counted(contents.revisions, "saved revision", "saved revisions")}`,
    contents.files > 0 && `${counted(contents.files, "picture, voice or music file", "pictures, voices and music files")}`,
    contents.characters > 0 && `${counted(contents.characters, "character", "characters")}`,
    contents.conversations > 0 && `${counted(contents.conversations, "conversation with the assistant", "conversations with the assistant")}`,
    contents.releases > 0 && `${counted(contents.releases, "released game", "released games")}, whose downloads will stop working`,
  ].filter((line): line is string => Boolean(line));
}

/** Why the button is not available yet, or null when it is. */
export function deletionBlocked(contents: ProjectContents): string | null {
  return contents.working.length
    ? `This project is still working on ${contents.working.join(" and ")}. You can delete it once that has finished.`
    : null;
}
