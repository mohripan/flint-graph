// Line delivery for generated voices (ADR 0045, #177): a bounded vocabulary with an
// intensity, defaulting from the line's sprite expression. Delivery is a generation
// input, never part of the story: the runtimes play clips and never speak. Mirrors
// the server's narrative/voice_models.py; the server checks every request again.

export const DELIVERIES = [
  "neutral", "happy", "angry", "sad", "afraid", "surprised", "whisper", "shout", "dramatic", "tender",
] as const;
export type DeliveryName = (typeof DELIVERIES)[number];
export interface Delivery { emotion: DeliveryName; intensity: number; tag: string | null }
export type Support = "full" | "approximate";
export interface DeliveryModel { name: string; deliveries: Record<string, Support>; tags: string[] }

export const NEUTRAL: Delivery = { emotion: "neutral", intensity: 0.5, tag: null };
export const DELIVERY_LABELS: Record<DeliveryName, string> = {
  neutral: "Neutral", happy: "Happy", angry: "Angry", sad: "Sad", afraid: "Afraid", surprised: "Surprised",
  whisper: "Whisper", shout: "Shout", dramatic: "Dramatic", tender: "Tender",
};
export const TAG_LABELS: Record<string, string> = {
  laugh: "laugh", chuckle: "chuckle", sigh: "sigh", gasp: "gasp", cough: "cough", groan: "groan",
  sniff: "sniff", shush: "shush", clear_throat: "clear throat",
};

// Expression presets (ADR 0041) that say how a line is meant: name → delivery, intensity.
const FROM_EXPRESSION: Record<string, [DeliveryName, number]> = {
  happy: ["happy", 0.5], laughing: ["happy", 0.9], smug: ["happy", 0.3],
  sad: ["sad", 0.5], crying: ["sad", 0.9], worried: ["afraid", 0.4], scared: ["afraid", 0.7],
  angry: ["angry", 0.6], furious: ["angry", 0.9], surprised: ["surprised", 0.6],
  determined: ["dramatic", 0.4], embarrassed: ["tender", 0.4], shy: ["tender", 0.4],
  sleepy: ["whisper", 0.3], whispering: ["whisper", 0.5], shouting: ["shout", 0.7],
};

/** What an expression implies, or neutral when it says nothing about the voice. */
export function deliveryFromExpression(expression: string | undefined | null): Delivery {
  const found = expression ? FROM_EXPRESSION[expression.trim().toLowerCase()] : undefined;
  return found ? { emotion: found[0], intensity: found[1], tag: null } : NEUTRAL;
}

/** The delivery a line is generated with: the creator's override, else its expression. */
export function lineDelivery(override: Delivery | undefined, expression: string | undefined | null):
  { delivery: Delivery; source: "override" | "expression" | "default" } {
  if (override) return { delivery: override, source: "override" };
  const implied = deliveryFromExpression(expression);
  return { delivery: implied, source: implied === NEUTRAL ? "default" : "expression" };
}

export function support(model: DeliveryModel | undefined, emotion: DeliveryName): Support | null {
  return model?.deliveries[emotion] ?? null;
}

/**
 * What this model really speaks for a wanted delivery: unsupported emotions and sounds
 * fall back to neutral, and ``note`` says so instead of hiding it.
 */
export function spokenDelivery(model: DeliveryModel | undefined, wanted: Delivery):
  { delivery: Delivery; note: string | null } {
  if (!model) return { delivery: wanted, note: null };
  const canEmotion = Boolean(model.deliveries[wanted.emotion]);
  const canTag = !wanted.tag || model.tags.includes(wanted.tag);
  const delivery: Delivery = {
    emotion: canEmotion ? wanted.emotion : "neutral",
    intensity: wanted.intensity,
    tag: canTag ? wanted.tag : null,
  };
  const missing = [
    !canEmotion && `speak a line ${DELIVERY_LABELS[wanted.emotion].toLowerCase()}`,
    !canTag && `make the sound “${TAG_LABELS[wanted.tag ?? ""] ?? wanted.tag}”`,
  ].filter(Boolean);
  const note = missing.length
    ? `${model.name} cannot ${missing.join(" or ")}; this clip will sound neutral. Choose a voice model that can in Characters.`
    : model.deliveries[wanted.emotion] === "approximate" && wanted.emotion !== "neutral"
      ? `${model.name} only approximates ${DELIVERY_LABELS[wanted.emotion].toLowerCase()}.`
      : null;
  return { delivery, note };
}

export function intensityLabel(intensity: number): string {
  return intensity < 0.34 ? "slightly" : intensity < 0.67 ? "moderately" : "strongly";
}
