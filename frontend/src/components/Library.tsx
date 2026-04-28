"use client";

/**
 * Tela biblioteca: grid de livros importados + botão de importar ZIP.
 *
 * Lê do IndexedDB no mount. Se vazia, exibe um prompt de importação.
 * Cada cartão linka para `/reader/<id>`.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { importBookFromZip, type ImportProgress } from "@/lib/import";
import { deleteBook, getProgress, listBooks } from "@/lib/storage";
import type { BookManifest, BookProgress } from "@/lib/types";

type BookCard = {
  manifest: BookManifest;
  progress: BookProgress | undefined;
};

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}min`;
  return `${m}min`;
}

function progressPercent(progress: BookProgress | undefined, totalDuration: number): number {
  if (!progress || totalDuration <= 0) return 0;
  // Aproximação: usa só o currentTime do último capítulo aberto em relação ao
  // total do livro. É um indicador, não medição exata. Refinamos quando precisar.
  const fraction = Math.min(progress.currentTime / totalDuration, 1);
  return Math.round(fraction * 100);
}

export function Library() {
  const [books, setBooks] = useState<BookCard[] | null>(null);
  const [importing, setImporting] = useState<ImportProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Carga inicial + recarga quando refreshTick muda (após import/delete).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const manifests = await listBooks();
      const cards = await Promise.all(
        manifests.map(async (m) => ({
          manifest: m,
          progress: await getProgress(m.id),
        })),
      );
      cards.sort((a, b) => {
        const ap = a.progress?.lastPlayedAt ?? 0;
        const bp = b.progress?.lastPlayedAt ?? 0;
        return bp - ap;
      });
      if (!cancelled) {
         
        setBooks(cards);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setImporting({ phase: "reading", current: 0, total: 1 });
    try {
      await importBookFromZip(file, (p) => setImporting(p));
      setRefreshTick((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setImporting(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (bookId: string, title: string) => {
    if (!confirm(`Apagar "${title}" da biblioteca?`)) return;
    await deleteBook(bookId);
    setRefreshTick((n) => n + 1);
  };

  return (
    <main className="flex-1 flex flex-col p-6 gap-6 max-w-4xl mx-auto w-full">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Biblioteca</h1>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={importing !== null}
          className="rounded-md bg-amber-500 text-neutral-950 px-4 py-2 text-sm font-medium disabled:opacity-50 hover:bg-amber-400 transition"
        >
          {importing ? "Importando..." : "+ Importar ZIP"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={handleFileChange}
        />
      </header>

      {importing && (
        <div className="rounded-md bg-neutral-900 border border-neutral-800 p-4 text-sm">
          <p className="text-neutral-300">
            {importing.phase === "reading" && "Lendo ZIP..."}
            {importing.phase === "validating" && "Validando book.json..."}
            {importing.phase === "extracting" &&
              `Extraindo (${importing.current}/${importing.total})${importing.filename ? ` — ${importing.filename}` : ""}`}
            {importing.phase === "done" && "Concluído."}
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-md bg-red-950 border border-red-900 p-4 text-sm text-red-200 whitespace-pre-wrap">
          <strong>Erro ao importar:</strong>
          <br />
          {error}
        </div>
      )}

      {books === null ? (
        <p className="text-neutral-500 text-sm">Carregando biblioteca...</p>
      ) : books.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {books.map((card) => (
            <BookCardView key={card.manifest.id} card={card} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </main>
  );
}

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center text-neutral-500 gap-2 py-16">
      <p className="text-lg">Sua biblioteca está vazia.</p>
      <p className="text-sm max-w-sm">
        Clique em <span className="text-amber-400">+ Importar ZIP</span> para
        adicionar um livro gerado pelo backend ReaderFree (
        <code className="text-neutral-400">backend/pipeline.py build ...</code>
        ).
      </p>
    </div>
  );
}

function BookCardView({
  card,
  onDelete,
}: {
  card: BookCard;
  onDelete: (id: string, title: string) => void;
}) {
  const { manifest, progress } = card;
  const pct = progressPercent(progress, manifest.duration_seconds);
  return (
    <div className="rounded-lg bg-neutral-900 border border-neutral-800 overflow-hidden flex flex-col">
      <Link
        href={`/reader/${encodeURIComponent(manifest.id)}`}
        className="p-4 flex flex-col gap-2 hover:bg-neutral-800/50 transition flex-1"
      >
        <h2 className="font-medium leading-tight">{manifest.title}</h2>
        <p className="text-sm text-neutral-400">
          {manifest.author ?? "—"} · {formatDuration(manifest.duration_seconds)} ·{" "}
          {manifest.chapters.length} capítulo{manifest.chapters.length !== 1 ? "s" : ""}
        </p>
        {progress && (
          <div className="mt-2">
            <div className="h-1 rounded-full bg-neutral-800 overflow-hidden">
              <div
                className="h-full bg-amber-500"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-xs text-neutral-500 mt-1">{pct}% lido</p>
          </div>
        )}
        {manifest.mock && (
          <span className="self-start text-xs px-2 py-0.5 rounded-full bg-yellow-900 text-yellow-200">
            mock
          </span>
        )}
      </Link>
      <button
        type="button"
        onClick={() => onDelete(manifest.id, manifest.title)}
        className="text-xs text-neutral-500 hover:text-red-400 px-4 py-2 border-t border-neutral-800 transition"
      >
        Apagar
      </button>
    </div>
  );
}
