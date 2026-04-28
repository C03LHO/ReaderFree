/**
 * Tipos espelhando o `book.json` gerado pelo backend.
 *
 * Schema documentado em `README.md` (raiz do repo) e implementado em
 * `backend/src/package.py::write_book_json`. Mantenha aqui em sincronia.
 */

/**
 * Entrada de capítulo (ou parte de capítulo dividido).
 *
 * `part` e `total_parts` aparecem só em capítulos longos divididos pela
 * Fase 2 (`chapter_split.py`). Capítulos únicos não trazem esses campos —
 * ausência = "capítulo único" (decidido na Fase 1.5).
 *
 * Capítulos divididos compartilham `id` e `title`; o par `(part, total_parts)`
 * diferencia. Ex: `id="livro-05", part=1, total_parts=3` é a parte 1/3 do
 * capítulo 5.
 */
export type ChapterEntry = {
  id: string;
  title: string;
  mp3_path: string;
  vtt_path: string;
  text_path: string;
  duration_seconds: number;
  word_count: number;
  part?: number;
  total_parts?: number;
};

/**
 * Top-level do `book.json`.
 */
export type BookManifest = {
  id: string;
  title: string;
  author: string | null;
  created_at: string; // ISO 8601
  duration_seconds: number;
  mock: boolean;
  chapters: ChapterEntry[];
};

/**
 * Estado de progresso de leitura para um livro.
 *
 * `chapterIndex` é o índice no array `chapters` (0-based, inclui partes
 * divididas como entradas separadas — coerente com o que o player itera).
 * `currentTime` é a posição atual em segundos dentro daquele áudio.
 */
export type BookProgress = {
  bookId: string;
  chapterIndex: number;
  currentTime: number;
  lastPlayedAt: number; // epoch ms
};

/**
 * Preferências globais do leitor (não por livro).
 */
export type Prefs = {
  playbackRate: number; // 0.75, 1.0, 1.25, 1.5, 2.0
};

export const DEFAULT_PREFS: Prefs = {
  playbackRate: 1.0,
};

/**
 * Validação runtime mínima de um manifest carregado do ZIP. Lança erro
 * com mensagem orientada ao usuário se algo essencial está ausente.
 */
export function validateManifest(data: unknown): BookManifest {
  if (!data || typeof data !== "object") {
    throw new Error("book.json não é um objeto JSON válido.");
  }
  const m = data as Record<string, unknown>;
  const required: Array<keyof BookManifest> = [
    "id",
    "title",
    "duration_seconds",
    "chapters",
  ];
  for (const field of required) {
    if (!(field in m)) {
      throw new Error(`book.json: campo obrigatório '${field}' ausente.`);
    }
  }
  if (!Array.isArray(m.chapters) || m.chapters.length === 0) {
    throw new Error("book.json: 'chapters' deve ser uma lista não-vazia.");
  }
  for (const [i, ch] of (m.chapters as unknown[]).entries()) {
    if (!ch || typeof ch !== "object") {
      throw new Error(`book.json: capítulo ${i} não é um objeto.`);
    }
    const c = ch as Record<string, unknown>;
    for (const f of ["id", "title", "mp3_path", "vtt_path", "text_path"]) {
      if (typeof c[f] !== "string" || !c[f]) {
        throw new Error(`book.json: capítulo ${i} sem '${f}'.`);
      }
    }
  }
  return data as BookManifest;
}
