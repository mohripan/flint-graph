import type { StoryDraft, StoryNode } from "./types";

// A scene ("passage") is what a writer thinks of as one stretch of script: consecutive
// lines and state changes, closed by the choice, condition or ending they lead into.
// It is an editor projection; the story still stores one node per line.
export interface Passage {
  id: string; nodes: string[]; exit: string | null;
  kind: "scene" | "choice" | "branch" | "end" | "state"; title: string; lines: number;
}

const linear = (node: StoryNode | undefined): node is Extract<StoryNode, { next: string }> =>
  node?.type === "line" || node?.type === "set";

function targets(node: StoryNode): string[] {
  switch (node.type) {
    case "line": case "set": return [node.next];
    case "choice": return node.options.map(option => option.target);
    case "branch": return [node.if_true, node.if_false];
    case "end": return [];
  }
}

function title(story: StoryDraft, ids: string[]): string {
  for (const id of ids) {
    const node = story.nodes[id];
    if (node && "text" in node && node.text.trim()) return node.text.trim().slice(0, 80);
  }
  const head = story.nodes[ids[0]];
  return head?.type === "branch" ? "Condition" : head?.type === "set" ? "State change" : "Untitled scene";
}

export function buildPassages(story: StoryDraft): {
  passages: Passage[]; owner: Map<string, string>; from: Map<string, string>;
} {
  const incoming = new Map<string, number>(), predecessor = new Map<string, string>();
  for (const [id, node] of Object.entries(story.nodes)) {
    for (const target of targets(node)) {
      incoming.set(target, (incoming.get(target) ?? 0) + 1);
      predecessor.set(target, id);
    }
  }
  const continues = (id: string) => {
    if (id === story.entry || incoming.get(id) !== 1) return false;
    const from = predecessor.get(id)!;
    return linear(story.nodes[from]);
  };
  const owner = new Map<string, string>(), passages: Passage[] = [];
  const walk = (head: string) => {
    const nodes = [head];
    owner.set(head, head);
    let current = head, exit: string | null = linear(story.nodes[head]) ? null : head;
    while (exit === null) {
      const node = story.nodes[current];
      if (!linear(node)) break;
      const next = node.next;
      if (!Object.prototype.hasOwnProperty.call(story.nodes, next) || owner.has(next) || !continues(next)) break;
      nodes.push(next); owner.set(next, head); current = next;
      if (!linear(story.nodes[next])) exit = next;
    }
    const kind: Passage["kind"] = linear(story.nodes[head])
      ? story.nodes[head].type === "set" && nodes.length === 1 ? "state" : "scene"
      : (story.nodes[head].type as "choice" | "branch" | "end");
    passages.push({ id: head, nodes, exit, kind, title: title(story, nodes),
      lines: nodes.filter(id => story.nodes[id]?.type === "line").length });
  };
  for (const id of Object.keys(story.nodes)) if (!continues(id)) walk(id);
  // Closed loops of single-entry lines have no natural head; start them in story order.
  for (const id of Object.keys(story.nodes)) if (!owner.has(id)) walk(id);
  // The scene a passage is reached from, used to place new scenes next to it.
  const from = new Map<string, string>();
  for (const passage of passages) {
    const previous = predecessor.get(passage.id), source = previous ? owner.get(previous) : undefined;
    if (source && source !== passage.id) from.set(passage.id, source);
  }
  return { passages, owner, from };
}
