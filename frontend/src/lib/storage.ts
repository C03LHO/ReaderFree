// Fase 4 — IndexedDB (via idb) para livros importados, progresso, preferências.
export type BookMeta = {
  id: string;
  title: string;
  author?: string;
  duration_seconds: number;
};

export async function listBooks(): Promise<BookMeta[]> {
  throw new Error("Implementar na Fase 4.");
}
