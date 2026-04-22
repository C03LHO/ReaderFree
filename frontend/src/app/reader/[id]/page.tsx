type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function ReaderPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main className="flex-1 flex flex-col items-center justify-center p-8 gap-4 text-center">
      <h1 className="text-2xl font-semibold">Reader</h1>
      <p className="text-neutral-400">
        Livro: <code className="text-neutral-200">{id}</code>
      </p>
      <p className="text-xs text-neutral-600">
        Fase 0 — esqueleto. Player + sincronização nas Fases 4 e 5.
      </p>
    </main>
  );
}
