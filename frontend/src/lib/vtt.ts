// Fase 5 — parser WebVTT para cues por palavra.
export type WordCue = {
  start: number;
  end: number;
  word: string;
  index: number;
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function parseVtt(raw: string): WordCue[] {
  throw new Error("Implementar na Fase 5.");
}
