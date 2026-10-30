type Entry = { snapshot: string; bytes: number };
const encoder = new TextEncoder();

export class DraftHistory {
  private back: Entry[] = [];
  private forward: Entry[] = [];
  private retained = 0;
  private group: string | null = null;

  constructor(private byteLimit = 8 * 1024 * 1024, private entryLimit = 50) {
    if (byteLimit < 1 || entryLimit < 1) throw new Error("History limits must be positive.");
  }
  get canUndo(): boolean { return this.back.length > 0; }
  get canRedo(): boolean { return this.forward.length > 0; }

  clear(): void {
    this.back = []; this.forward = []; this.retained = 0; this.group = null;
  }
  breakGroup(): void { this.group = null; }

  // A thunk defers building large snapshots until a new undo step is actually recorded.
  record(value: string | (() => string), group?: string): void {
    if (group && this.group === group) return;
    const snapshot = typeof value === "function" ? value() : value;
    for (const entry of this.forward) this.retained -= entry.bytes;
    this.forward = [];
    const entry = this.entry(snapshot);
    if (entry.bytes > this.byteLimit) { this.clear(); return; }
    if (this.back[this.back.length - 1]?.snapshot !== snapshot) {
      this.back.push(entry); this.retained += entry.bytes;
    }
    this.group = group ?? null;
    this.trim();
  }

  undo(current: string): string | null {
    return this.move(this.back, this.forward, current);
  }
  redo(current: string): string | null {
    return this.move(this.forward, this.back, current);
  }

  private entry(snapshot: string): Entry {
    return { snapshot, bytes: encoder.encode(snapshot).byteLength };
  }
  private move(from: Entry[], to: Entry[], current: string): string | null {
    this.group = null;
    let entry: Entry | undefined;
    while ((entry = from.pop())) {
      this.retained -= entry.bytes;
      if (entry.snapshot !== current) break;
    }
    if (!entry || entry.snapshot === current) return null;
    const present = this.entry(current);
    if (present.bytes <= this.byteLimit) { to.push(present); this.retained += present.bytes; }
    this.trim();
    return entry.snapshot;
  }
  private trim(): void {
    while (this.retained > this.byteLimit || this.back.length + this.forward.length > this.entryLimit) {
      const removed = this.back.length ? this.back.shift() : this.forward.shift();
      if (!removed) break;
      this.retained -= removed.bytes;
    }
  }
}
