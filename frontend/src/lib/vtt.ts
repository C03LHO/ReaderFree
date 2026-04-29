/**
 * Parser de WebVTT word-level + busca binária do cue ativo.
 *
 * Formato esperado (gerado pelo backend `package.write_vtt`):
 *
 *     WEBVTT
 *
 *     00:00:00.163 --> 00:00:00.572
 *     verme
 *
 *     00:00:00.572 --> 00:00:00.817
 *     que
 *
 * Cada cue é uma palavra. Timestamps em `HH:MM:SS.mmm`.
 *
 * O parser é tolerante: ignora cues sem timestamp ou sem texto, ignora notas
 * "NOTE ..." da spec, aceita CR/LF de qualquer plataforma. Não suporta
 * `<voice>` tags ou estilos — não temos isso no nosso pipeline.
 */

export type WordCue = {
  start: number; // segundos
  end: number; // segundos
  word: string;
  index: number; // 0-based, posição no array
};

const TIMESTAMP_LINE = /^\s*(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})/;

/**
 * Parsa um arquivo WebVTT em `WordCue[]` na ordem original.
 *
 * Cues sem timestamp válido ou sem texto são silenciosamente descartados;
 * o `index` é reatribuído sequencialmente após o filtro para que a busca
 * binária e o render por posição fiquem coerentes.
 */
export function parseVtt(raw: string): WordCue[] {
  const normalized = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const blocks = normalized.split(/\n\s*\n/);
  const cues: WordCue[] = [];
  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;
    if (/^WEBVTT\b/i.test(trimmed)) continue;
    if (/^NOTE\b/i.test(trimmed)) continue;

    const lines = trimmed.split("\n");
    // Primeira linha pode ser um identificador opcional; a linha de
    // timestamp pode estar na 1ª ou na 2ª.
    let timestampIdx = -1;
    let timestampMatch: RegExpExecArray | RegExpMatchArray | null = null;
    for (let i = 0; i < Math.min(lines.length, 2); i++) {
      const m = TIMESTAMP_LINE.exec(lines[i]);
      if (m) {
        timestampIdx = i;
        timestampMatch = m;
        break;
      }
    }
    if (!timestampMatch || timestampIdx < 0) continue;

    const start = parseTimestamp(timestampMatch[1]);
    const end = parseTimestamp(timestampMatch[2]);
    if (Number.isNaN(start) || Number.isNaN(end)) continue;

    const text = lines
      .slice(timestampIdx + 1)
      .join(" ")
      .trim();
    if (!text) continue;

    cues.push({ start, end, word: text, index: cues.length });
  }
  return cues;
}

/**
 * Converte `HH:MM:SS.mmm` para segundos.
 *
 * Retorna NaN se a string não bate com o formato esperado — o caller
 * decide se descarta o cue ou propaga o erro.
 */
export function parseTimestamp(stamp: string): number {
  const m = /^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$/.exec(stamp.trim());
  if (!m) return Number.NaN;
  const h = Number(m[1]);
  const min = Number(m[2]);
  const s = Number(m[3]);
  const ms = Number(m[4]);
  return h * 3600 + min * 60 + s + ms / 1000;
}

/**
 * Busca binária pelo cue ativo no tempo `time` (segundos).
 *
 * Comportamento por região:
 *   - `time < cues[0].start` → retorna `-1` (antes da primeira palavra).
 *   - `cues[i].start <= time < cues[i].end` → retorna `i` (palavra ativa).
 *   - `cues[i].end <= time < cues[i+1].start` → retorna `i` (gap entre
 *     palavras: mantém highlight na palavra mais recente até a próxima
 *     começar — comportamento natural pra leitor).
 *   - `time >= cues[last].end` → retorna `last`. (Importante: o backend
 *     deixa ~500 ms de trailing silence depois da última palavra; sem
 *     este caso, o highlight piscaria pra fora no fim do capítulo.
 *     Detalhe documentado em `backend/src/align.py`.)
 *
 * Lista vazia retorna `-1`. Implementação O(log n) — capítulos de 8000
 * palavras precisam só de ~13 comparações por frame.
 */
export function findActiveCueIndex(cues: WordCue[], time: number): number {
  if (cues.length === 0) return -1;
  if (time < cues[0].start) return -1;

  let lo = 0;
  let hi = cues.length - 1;
  let lastEnded = -1; // último cue cuja .end <= time
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const c = cues[mid];
    if (time < c.start) {
      hi = mid - 1;
    } else if (time >= c.end) {
      lastEnded = mid;
      lo = mid + 1;
    } else {
      // start <= time < end → cue ativo.
      return mid;
    }
  }
  // Estamos num gap (entre `cues[lastEnded].end` e `cues[lastEnded+1].start`)
  // ou depois da última palavra. Mantém o highlight na palavra anterior.
  return lastEnded;
}
