import type { Condition, StoryDraft, StoryNode, VariableDeclaration } from "./types";

export function own<T>(record: Record<string, T>, key: string): T | undefined {
  return Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined;
}

export function getScene(story: StoryDraft, id: string): StoryNode | undefined {
  return own(story.nodes, id);
}

function availableId(prefix: string, occupied: Iterable<string>): string {
  const used = new Set(occupied);
  let number = 1;
  while (used.has(`${prefix}_${number}`)) number += 1;
  return `${prefix}_${number}`;
}

function textIds(story: StoryDraft): string[] {
  return Object.values(story.nodes).flatMap(node => {
    if (node.type === "line" || node.type === "end") return [node.text_id];
    if (node.type === "choice") return [node.text_id, ...node.options.map(option => option.text_id)];
    return [];
  });
}

export function addScene(story: StoryDraft, kind: StoryNode["type"]): {
  story: StoryDraft; id: string;
} {
  if (Object.keys(story.nodes).length >= 10000) throw new Error("This story already has 10,000 scenes.");
  const next = structuredClone(story);
  const id = availableId(kind === "line" ? "scene" : kind === "end" ? "ending" : kind,
    Object.keys(story.nodes));
  const usedText = textIds(story);
  const textId = availableId(`${id}_text`, usedText);
  usedText.push(textId);
  const target = Object.entries(story.nodes).find(([, node]) => node.type === "end")?.[0] ?? story.entry;
  let node: StoryNode;
  if (kind === "line") {
    node = { type: "line", text_id: textId, text: "A new scene begins.", next: target };
  } else if (kind === "end") {
    const endings = Object.values(story.nodes).flatMap(item => item.type === "end" ? [item.ending] : []);
    node = { type: "end", text_id: textId, text: "The end.", ending: availableId("ending", endings) };
  } else if (kind === "choice") {
    node = { type: "choice", text_id: textId, text: "What happens next?", options: [1, 2].map(index => ({
      id: `option_${index}`, text_id: availableId(`${id}_option_${index}_text`, usedText),
      text: index === 1 ? "Follow the first path." : "Follow another path.", target,
    })) };
  } else {
    const [variable] = Object.keys(story.variables);
    if (!variable) throw new Error("Add a variable before creating a state change or condition.");
    const condition = defaultCondition(story, variable);
    node = kind === "set"
      ? { type: "set", operations: [{ op: "set", variable, value: story.variables[variable].initial }], next: target }
      : { type: "branch", condition, if_true: target, if_false: target };
  }
  next.nodes[id] = node;
  return { story: next, id };
}

export function addVariable(story: StoryDraft, type: VariableDeclaration["type"]): {
  story: StoryDraft; id: string;
} {
  if (Object.keys(story.variables).length >= 256) throw new Error("This story already has 256 variables.");
  const id = availableId("state", Object.keys(story.variables));
  const declaration: VariableDeclaration = type === "enum"
    ? { type, values: ["first", "second"], initial: "first" }
    : { type, initial: type === "bool" ? false : 0 };
  return { id, story: { ...story, variables: { ...story.variables, [id]: declaration } } };
}

export function defaultCondition(story: StoryDraft, variable?: string): Condition {
  const id = variable ?? Object.keys(story.variables)[0];
  const declaration = id ? own(story.variables, id) : undefined;
  if (!declaration) throw new Error("Add a variable before creating a condition.");
  return { op: "eq", variable: id, value: declaration.initial };
}

export function sceneTargets(node: StoryNode): string[] {
  switch (node.type) {
    case "line": case "set": return [node.next];
    case "choice": return node.options.map(option => option.target);
    case "branch": return [node.if_true, node.if_false];
    case "end": return [];
  }
}

export function deleteScene(story: StoryDraft, id: string): StoryDraft {
  if (!getScene(story, id)) throw new Error("Scene no longer exists.");
  if (id === story.entry) throw new Error("Choose another entry scene before deleting this one.");
  if (Object.entries(story.nodes).some(([from, node]) => from !== id && sceneTargets(node).includes(id))) {
    throw new Error("This scene is still referenced. Reconnect its incoming routes first.");
  }
  const nodes = { ...story.nodes };
  delete nodes[id];
  return { ...story, nodes };
}

export function replaceScene(story: StoryDraft, id: string, node: StoryNode): StoryDraft {
  if (!getScene(story, id)) throw new Error("Scene no longer exists.");
  return { ...story, nodes: { ...story.nodes, [id]: node } };
}

export function addChoiceOption(story: StoryDraft, id: string): StoryDraft {
  const node = getScene(story, id);
  if (!node || node.type !== "choice") throw new Error("Choose a choice scene first.");
  if (node.options.length >= 32) throw new Error("A choice can contain at most 32 options.");
  const option = { id: availableId("option", node.options.map(item => item.id)),
    text_id: availableId(`${id.slice(0, 36)}_option_text`, textIds(story)),
    text: "Follow this path.", target: node.options[0]?.target ?? story.entry };
  return replaceScene(story, id, { ...node, options: [...node.options, option] });
}

export function addCharacter(story: StoryDraft): { story: StoryDraft; id: string } {
  if (Object.keys(story.characters).length >= 256) throw new Error("This story already has 256 characters.");
  const id = availableId("character", Object.keys(story.characters));
  return { id, story: { ...story, characters: { ...story.characters, [id]: { name: "New character" } } } };
}

export function checkCondition(value: Condition): Condition {
  const pending = [{ value, depth: 1 }];
  let count = 0;
  while (pending.length) {
    const item = pending.pop()!;
    count += 1;
    if (item.depth > 8) throw new Error("Conditions can be nested at most eight levels.");
    if (count > 64) throw new Error("A condition can contain at most 64 checks.");
    if (item.value.op === "all" || item.value.op === "any") {
      if (!item.value.children.length) throw new Error("A condition group needs at least one check.");
      for (const child of item.value.children) pending.push({ value: child, depth: item.depth + 1 });
    } else if (item.value.op === "not") {
      pending.push({ value: item.value.child, depth: item.depth + 1 });
    }
  }
  return value;
}

export function deleteCharacter(story: StoryDraft, id: string): StoryDraft {
  if (!own(story.characters, id)) throw new Error("Character no longer exists.");
  if (Object.values(story.nodes).some(node => node.type === "line" && node.speaker === id)) {
    throw new Error("This character is still referenced as a speaker. Change those scenes first.");
  }
  const characters = { ...story.characters }; delete characters[id];
  return { ...story, characters };
}

export function deleteVariable(story: StoryDraft, id: string): StoryDraft {
  if (!own(story.variables, id)) throw new Error("Variable no longer exists.");
  const conditions: Condition[] = [];
  for (const node of Object.values(story.nodes)) {
    if (node.type === "set" && node.operations.some(operation => operation.variable === id)) {
      throw new Error("This variable is still referenced by a state change.");
    }
    if (node.type === "branch") conditions.push(node.condition);
    if (node.type === "choice") for (const option of node.options) {
      if (option.condition) conditions.push(option.condition);
    }
  }
  while (conditions.length) {
    const condition = conditions.pop()!;
    if (condition.op === "all" || condition.op === "any") conditions.push(...condition.children);
    else if (condition.op === "not") conditions.push(condition.child);
    else if ("variable" in condition && condition.variable === id) {
      throw new Error("This variable is still referenced by a condition.");
    }
  }
  const variables = { ...story.variables }; delete variables[id];
  return { ...story, variables };
}

// Inserting a line keeps it inside the same scene and with the same speaker.
export function insertLineAfter(story: StoryDraft, id: string): { story: StoryDraft; id: string } {
  const node = getScene(story, id);
  if (!node || (node.type !== "line" && node.type !== "set")) throw new Error("Only lines and state changes can be followed by a new line.");
  if (Object.keys(story.nodes).length >= 10000) throw new Error("This story already has 10,000 scenes.");
  const lineId = availableId(`${id.slice(0, 48)}_line`, Object.keys(story.nodes));
  const textId = availableId(`${lineId}_text`, textIds(story));
  const speaker = node.type === "line" ? node.speaker : undefined;
  const line: StoryNode = { type: "line", text_id: textId, text: "…", next: node.next, ...(speaker ? { speaker } : {}) };
  return { id: lineId, story: { ...story, nodes: { ...story.nodes, [id]: { ...node, next: lineId }, [lineId]: line } } };
}

// Removing a line reconnects every route that reached it to the line that followed it.
export function removeLine(story: StoryDraft, id: string): StoryDraft {
  const node = getScene(story, id);
  if (!node || (node.type !== "line" && node.type !== "set")) throw new Error("Only lines and state changes can be removed here.");
  if (node.next === id) throw new Error("This line loops to itself; reconnect it first.");
  const follow = (target: string) => target === id ? node.next : target;
  const nodes: Record<string, StoryNode> = {};
  for (const [key, item] of Object.entries(story.nodes)) {
    if (key === id) continue;
    nodes[key] = item.type === "line" || item.type === "set" ? { ...item, next: follow(item.next) }
      : item.type === "choice" ? { ...item, options: item.options.map(option => ({ ...option, target: follow(option.target) })) }
      : item.type === "branch" ? { ...item, if_true: follow(item.if_true), if_false: follow(item.if_false) } : item;
  }
  return { ...story, entry: follow(story.entry), nodes };
}
// Deletes a whole scene's nodes when nothing outside the scene still leads into it.
export function deletePassage(story: StoryDraft, ids: string[]): StoryDraft {
  const doomed = new Set(ids);
  if (doomed.has(story.entry)) throw new Error("This scene starts the story. Choose another start scene first.");
  for (const [id, node] of Object.entries(story.nodes)) {
    if (!doomed.has(id) && sceneTargets(node).some(target => doomed.has(target))) {
      throw new Error("Other scenes still lead here. Reconnect those routes first.");
    }
  }
  const nodes = { ...story.nodes };
  for (const id of doomed) delete nodes[id];
  return { ...story, nodes };
}