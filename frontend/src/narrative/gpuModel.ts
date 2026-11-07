// What people are told when the GPU is not up (ADR 0069). The server says what the state is;
// this words it. It is a little silly on purpose, and always true.
export type GpuKind = "image" | "voice" | "pose" | "style" | "assistant";
export interface GpuStatus {
  state: "ready" | "asleep" | "starting" | "stopping" | "unavailable" | "off";
  detail: string | null; wake_seconds: number | null; waiting: string[];
}
export interface GpuMessage { title: string; body: string; bad: boolean }

const WORKERS: Record<GpuKind, string> = { image: "picture", voice: "voice", pose: "pose", style: "training", assistant: "assistant" };
const THRIFT = "We switch it off when nobody is using it, to save money";

export function wakeTime(seconds: number | null): string {
  if (!seconds) return "a few minutes";
  return seconds < 90 ? "about a minute" : `about ${Math.round(seconds / 60)} minutes`;
}

/** What to say about these kinds of work, or null when none of them would wait. */
export function gpuMessage(status: GpuStatus | null, kinds: GpuKind[]): GpuMessage | null {
  const waiting = status ? kinds.filter(kind => status.waiting.includes(kind)) : [];
  if (!status || !waiting.length) return null;
  const time = wakeTime(status.wake_seconds);
  switch (status.state) {
    case "asleep": return {
      title: "The GPU is taking a nap.", bad: false,
      body: `${THRIFT}, so the first request waits ${time} while it wakes up. It then starts by itself, and you can keep writing meanwhile.`,
    };
    case "starting": return {
      title: "Waking the GPU… it is not a morning person.", bad: false,
      body: `${THRIFT}, so this takes ${time}. Your request starts by itself, and you can keep writing meanwhile.`,
    };
    case "stopping": return {
      title: "The GPU was just dozing off.", bad: false,
      body: "It has to finish going to sleep before it can wake up again, so this takes a little longer. Your request stays in line.",
    };
    case "unavailable":
      if (status.detail === "no_capacity") return {
        title: "No GPU is free right now.", bad: true,
        body: "The cloud has none to lend us at the moment. We keep asking, and your request stays in line.",
      };
      if (status.detail === "daily_cap") return {
        title: "The GPU has clocked off for today.", bad: true,
        body: "It reached today's limit on GPU hours, which keeps costs in check. Your request stays in line.",
      };
      return {
        title: "The GPU won't wake up.", bad: true,
        body: "Something is wrong on our side. Your request stays in line and starts once it's fixed.",
      };
    case "off": {
      const names = waiting.map(kind => WORKERS[kind]).join(" and ");
      return {
        title: `The ${names} worker${waiting.length > 1 ? "s aren't" : " isn't"} running.`, bad: true,
        body: "Your request stays in line and starts when it's back.",
      };
    }
    default: return null;
  }
}

const ACTION_KINDS: Record<string, GpuKind> = { generate_voice: "voice", start_child_session: "assistant" };
/** The work an assistant action waits on. */
export const actionGpuKind = (op: string): GpuKind => ACTION_KINDS[op] ?? "image";
