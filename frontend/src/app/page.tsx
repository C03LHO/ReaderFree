export default function Home() {
  return (
    <main className="flex-1 flex flex-col items-center justify-center p-8 gap-4 text-center">
      <h1 className="text-3xl font-semibold">ReaderFree</h1>
      <p className="text-neutral-400 max-w-sm">
        Audiobook player pessoal com texto sincronizado palavra a palavra.
      </p>
      <p className="text-xs text-neutral-600">
        Fase 0 — esqueleto. A biblioteca será implementada na Fase 4.
      </p>
    </main>
  );
}
