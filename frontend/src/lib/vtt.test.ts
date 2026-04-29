import { describe, expect, it } from "vitest";

import { findActiveCueIndex, parseTimestamp, parseVtt } from "./vtt";

// =============================================================================
// parseTimestamp
// =============================================================================

describe("parseTimestamp", () => {
  it("converte HH:MM:SS.mmm para segundos", () => {
    expect(parseTimestamp("00:00:00.000")).toBe(0);
    expect(parseTimestamp("00:00:01.500")).toBe(1.5);
    expect(parseTimestamp("00:01:00.000")).toBe(60);
    expect(parseTimestamp("01:00:00.000")).toBe(3600);
    expect(parseTimestamp("01:23:45.678")).toBeCloseTo(3600 + 23 * 60 + 45.678, 5);
  });

  it("tolera espaços ao redor", () => {
    expect(parseTimestamp("  00:00:01.500  ")).toBe(1.5);
  });

  it("retorna NaN para formato inválido", () => {
    expect(parseTimestamp("garbage")).toBeNaN();
    expect(parseTimestamp("00:00:01")).toBeNaN(); // sem milissegundos
    expect(parseTimestamp("0:0:1.500")).toBeNaN(); // sem zero-pad
  });
});

// =============================================================================
// parseVtt
// =============================================================================

const SAMPLE_VTT = `WEBVTT

00:00:00.000 --> 00:00:00.163
Ao

00:00:00.163 --> 00:00:00.572
verme

00:00:00.572 --> 00:00:00.817
que
`;

describe("parseVtt", () => {
  it("parsa o sample de Brás Cubas", () => {
    const cues = parseVtt(SAMPLE_VTT);
    expect(cues).toHaveLength(3);
    expect(cues[0]).toEqual({ start: 0, end: 0.163, word: "Ao", index: 0 });
    expect(cues[1]).toEqual({ start: 0.163, end: 0.572, word: "verme", index: 1 });
    expect(cues[2]).toEqual({ start: 0.572, end: 0.817, word: "que", index: 2 });
  });

  it("aceita CRLF", () => {
    const crlf = SAMPLE_VTT.replace(/\n/g, "\r\n");
    expect(parseVtt(crlf)).toHaveLength(3);
  });

  it("aceita CR puro (Mac antigo)", () => {
    const cr = SAMPLE_VTT.replace(/\n/g, "\r");
    expect(parseVtt(cr)).toHaveLength(3);
  });

  it("ignora bloco WEBVTT e notas NOTE", () => {
    const vtt = `WEBVTT

NOTE Isto é uma nota descritiva
que pode atravessar linhas.

00:00:00.000 --> 00:00:00.500
palavra
`;
    const cues = parseVtt(vtt);
    expect(cues).toHaveLength(1);
    expect(cues[0].word).toBe("palavra");
  });

  it("aceita identificador opcional antes do timestamp", () => {
    const vtt = `WEBVTT

cue-1
00:00:00.000 --> 00:00:00.500
primeira
`;
    const cues = parseVtt(vtt);
    expect(cues).toHaveLength(1);
    expect(cues[0].word).toBe("primeira");
  });

  it("descarta cues sem texto", () => {
    const vtt = `WEBVTT

00:00:00.000 --> 00:00:00.500

00:00:00.500 --> 00:00:01.000
ok
`;
    const cues = parseVtt(vtt);
    expect(cues).toHaveLength(1);
    expect(cues[0].word).toBe("ok");
  });

  it("descarta cues com timestamp inválido", () => {
    const vtt = `WEBVTT

99:99:99 --> 88:88:88
ignorada

00:00:00.500 --> 00:00:01.000
mantida
`;
    const cues = parseVtt(vtt);
    expect(cues).toHaveLength(1);
    expect(cues[0].word).toBe("mantida");
  });

  it("re-numera índices após filtros", () => {
    const vtt = `WEBVTT

00:00:00.000 --> 00:00:00.100

00:00:00.100 --> 00:00:00.200
a

00:00:00.200 --> 00:00:00.300
b
`;
    const cues = parseVtt(vtt);
    expect(cues.map((c) => c.index)).toEqual([0, 1]);
    expect(cues.map((c) => c.word)).toEqual(["a", "b"]);
  });

  it("VTT vazio retorna lista vazia", () => {
    expect(parseVtt("")).toEqual([]);
    expect(parseVtt("WEBVTT\n")).toEqual([]);
  });

  it("preserva acentos e palavras com pontuação", () => {
    const vtt = `WEBVTT

00:00:00.000 --> 00:00:00.500
Memórias

00:00:00.500 --> 00:00:01.000
Póstumas,
`;
    const cues = parseVtt(vtt);
    expect(cues[0].word).toBe("Memórias");
    expect(cues[1].word).toBe("Póstumas,");
  });
});

// =============================================================================
// findActiveCueIndex
// =============================================================================

describe("findActiveCueIndex", () => {
  const cues = parseVtt(SAMPLE_VTT);
  // cues = [
  //   { start: 0,     end: 0.163, word: "Ao",    index: 0 },
  //   { start: 0.163, end: 0.572, word: "verme", index: 1 },
  //   { start: 0.572, end: 0.817, word: "que",   index: 2 },
  // ]

  it("retorna -1 se lista vazia", () => {
    expect(findActiveCueIndex([], 0)).toBe(-1);
    expect(findActiveCueIndex([], 5)).toBe(-1);
  });

  it("retorna -1 antes da primeira palavra (e o start é estritamente positivo)", () => {
    const cues2 = parseVtt(`WEBVTT\n\n00:00:00.500 --> 00:00:01.000\noi\n`);
    expect(findActiveCueIndex(cues2, 0)).toBe(-1);
    expect(findActiveCueIndex(cues2, 0.499)).toBe(-1);
  });

  it("retorna 0 no exato start do primeiro cue", () => {
    expect(findActiveCueIndex(cues, 0)).toBe(0);
  });

  it("retorna o índice do cue ativo no meio", () => {
    expect(findActiveCueIndex(cues, 0.1)).toBe(0);
    expect(findActiveCueIndex(cues, 0.3)).toBe(1);
    expect(findActiveCueIndex(cues, 0.7)).toBe(2);
  });

  it("retorna o índice anterior em gap entre palavras", () => {
    // Constrói cues com gap explícito.
    const gapped = parseVtt(`WEBVTT

00:00:00.000 --> 00:00:00.500
um

00:00:01.000 --> 00:00:01.500
dois
`);
    expect(findActiveCueIndex(gapped, 0.7)).toBe(0); // no gap, mantém em "um"
    expect(findActiveCueIndex(gapped, 1.0)).toBe(1); // exato start de "dois"
  });

  it("retorna o último cue depois do fim (trailing silence do XTTS)", () => {
    // Documentado em backend/src/align.py: ~500ms de cauda após a última palavra.
    expect(findActiveCueIndex(cues, 1.0)).toBe(2);
    expect(findActiveCueIndex(cues, 100)).toBe(2);
  });

  it("é determinístico em capítulos longos (sanity para busca binária)", () => {
    // Constrói 1000 cues sintéticos espaçados por 0.1s sem gaps.
    const longCues = Array.from({ length: 1000 }, (_, i) => ({
      start: i * 0.1,
      end: (i + 1) * 0.1,
      word: `w${i}`,
      index: i,
    }));
    // Pontos arbitrários — sempre cai no índice esperado.
    expect(findActiveCueIndex(longCues, 0)).toBe(0);
    expect(findActiveCueIndex(longCues, 49.95)).toBe(499);
    expect(findActiveCueIndex(longCues, 99.95)).toBe(999);
    expect(findActiveCueIndex(longCues, 200)).toBe(999); // depois do fim
  });
});
