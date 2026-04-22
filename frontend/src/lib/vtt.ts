// Fase 5 — parser WebVTT para cues por palavra.
export type WordCue = {
  start: number;
  end: number;
  word: string;
  index: number;
};

export function parseVtt(_raw: string): WordCue[] {
  throw new Error("Implementar na Fase 5.");
}
