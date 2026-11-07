// The first-time guide: one way through the Studio, from an empty page to a game someone can play.

export interface GuideStep { title: string; text: string }

export const GUIDE_STEPS: GuideStep[] = [
  { title: "Start a story", text: "Give your project a name. You can change it whenever you like." },
  {
    title: "Tell the Assistant what you want",
    text: "Open Assistant and describe your story in your own words, like “a short mystery on a night ferry, with one big choice.” It writes the scenes and shows you what it would change. Nothing is saved until you press Accept.",
  },
  {
    title: "Make the pictures and voices",
    text: "Ask for them in the chat, or use Characters and Assets for more control. Each one shows what it will cost and waits for you to press Generate. You pick the version you like and put it on stage.",
  },
  { title: "Play it", text: "Press Playtest at the top of the page to play your game right here, as often as you want. Playtests are free." },
  { title: "Share it", text: "When you are happy with it, Releases builds a game you can download and share with anyone." },
];

const SEEN_KEY = "flintgraph.guide.seen";

/** Private windows and blocked storage can throw: a guide shown twice is only a small annoyance. */
export function guideSeen(storage: Pick<Storage, "getItem"> | null): boolean {
  try { return storage?.getItem(SEEN_KEY) === "1"; } catch { return false; }
}

export function markGuideSeen(storage: Pick<Storage, "setItem"> | null): void {
  try { storage?.setItem(SEEN_KEY, "1"); } catch { /* Shown again next time, which does no harm. */ }
}
