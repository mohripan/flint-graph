// Voice reference audio in the browser (#175, ADR 0045): recordings and uploads become
// 24 kHz mono 16-bit WAV before they are sent, the form the server stores. The server
// checks length, clipping and silence again and decides.

export const REFERENCE_RATE = 24000;
export const MIN_SECONDS = 5;
export const MAX_SECONDS = 30;

/** Canonical mono 16-bit PCM WAV bytes for samples in [-1, 1]. */
export function encodeWav(samples: Float32Array, rate = REFERENCE_RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, Math.round(value < 0 ? value * 32768 : value * 32767), true);
  }
  return buffer;
}

/** Why a reference would be refused before uploading it, or null. Mirrors the server. */
export function referenceProblem(samples: Float32Array, rate = REFERENCE_RATE): string | null {
  const seconds = samples.length / rate;
  if (seconds < MIN_SECONDS) return `A reference needs at least ${MIN_SECONDS} seconds of speech.`;
  if (seconds > MAX_SECONDS) return `Keep the reference to at most ${MAX_SECONDS} seconds; trim it first.`;
  let clipped = 0;
  for (const value of samples) if (Math.abs(value) >= 0.99997) clipped++;
  if (clipped > samples.length * 0.001) return "The recording is clipped (too loud). Record again a little further from the microphone.";
  const window = Math.round(rate * 0.05);
  let heard = 0;
  for (let start = 0; start + window <= samples.length; start += window) {
    let energy = 0;
    for (let i = start; i < start + window; i++) energy += samples[i] * samples[i];
    if (Math.sqrt(energy / window) >= 0.01) heard++;
  }
  return heard * 0.05 < 2 ? "We could barely hear anyone. Record closer to the microphone in a quiet room." : null;
}

/** Decode any audio the browser can read and mix it down to 24 kHz mono. */
export async function toReferenceSamples(data: ArrayBuffer): Promise<Float32Array> {
  const decoder = new AudioContext();
  try {
    const decoded = await decoder.decodeAudioData(data.slice(0));
    const frames = Math.ceil(decoded.duration * REFERENCE_RATE);
    const offline = new OfflineAudioContext(1, Math.max(1, frames), REFERENCE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    return (await offline.startRendering()).getChannelData(0);
  } finally { await decoder.close(); }
}
