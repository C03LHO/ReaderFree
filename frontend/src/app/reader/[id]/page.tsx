"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { Player } from "@/components/Player";
import { getBook } from "@/lib/storage";
import type { BookManifest } from "@/lib/types";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default function ReaderPage({ params }: PageProps) {
  const { id } = use(params);
  const bookId = decodeURIComponent(id);
  const [manifest, setManifest] = useState<BookManifest | null | "missing">(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const book = await getBook(bookId);
      if (cancelled) return;
      setManifest(book ?? "missing");
    })();
    return () => {
      cancelled = true;
    };
  }, [bookId]);

  if (manifest === null) {
    return (
      <main className="flex-1 flex items-center justify-center p-8 text-neutral-500 text-sm">
        Carregando livro...
      </main>
    );
  }
  if (manifest === "missing") {
    return (
      <main className="flex-1 flex flex-col items-center justify-center p-8 gap-3 text-center">
        <p className="text-neutral-300">
          Livro <code className="text-neutral-100">{bookId}</code> não encontrado na biblioteca.
        </p>
        <Link href="/" className="text-amber-400 hover:underline text-sm">
          ← Voltar à biblioteca
        </Link>
      </main>
    );
  }
  return <Player manifest={manifest} />;
}
