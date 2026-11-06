// Conversations as a tree: parents with child sessions under them (ADR 0063).
import type { AssistantThread } from "./types";

export interface ThreadRow extends AssistantThread {
  depth: number; last: boolean; childCount: number; busy: boolean; open: boolean;
}

export function findThread(roots: AssistantThread[], id: string | null): AssistantThread | undefined {
  if (!id) return undefined;
  for (const root of roots) {
    if (root.id === id) return root;
    const child = root.children?.find(item => item.id === id);
    if (child) return child;
  }
  return undefined;
}

/** The rows the sidebar shows. A parent opens by itself when it or its child is the open
 *  conversation, and a click flips that. One with a child working always stays open, so a
 *  spinner is never hidden. */
export function visibleThreads(roots: AssistantThread[], toggled: Set<string>, current: string | null): ThreadRow[] {
  const rows: ThreadRow[] = [];
  for (const root of roots) {
    const children = root.children ?? [];
    const busy = children.some(child => child.active);
    const auto = root.id === current || children.some(child => child.id === current);
    const open = busy || (toggled.has(root.id) ? !auto : auto);
    rows.push({ ...root, depth: 0, last: false, childCount: children.length, busy, open });
    if (open) children.forEach((child, index) => rows.push({
      ...child, depth: 1, last: index === children.length - 1, childCount: 0, busy: false, open: false,
    }));
  }
  return rows;
}

/** A refreshed first page replaces the list, keeping threads only this page knows so far. */
export function mergeThreads(known: AssistantThread[], incoming: AssistantThread[], { keepIds }: { keepIds: Set<string> }): AssistantThread[] {
  const fresh = new Set(incoming.map(row => row.id));
  return [...known.filter(row => keepIds.has(row.id) && !fresh.has(row.id)), ...incoming]
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}
export function appendThreads(known: AssistantThread[], older: AssistantThread[]): AssistantThread[] {
  return [...known, ...older.filter(row => !known.some(item => item.id === row.id))];
}

/** Put one thread where it belongs: a root first, a child under its parent. */
export function placeThread(roots: AssistantThread[], thread: AssistantThread): AssistantThread[] {
  if (!thread.parent_thread_id) {
    return roots.some(row => row.id === thread.id)
      ? roots.map(row => row.id === thread.id ? { ...row, ...thread, children: row.children ?? [] } : row)
      : [thread, ...roots];
  }
  return roots.map(row => {
    if (row.id !== thread.parent_thread_id) return row;
    const children = row.children ?? [];
    return children.some(item => item.id === thread.id) ? row : { ...row, children: [...children, thread] };
  });
}
