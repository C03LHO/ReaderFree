"use client";

/**
 * Player de áudio + texto do capítulo.
 *
 * Recebe o livro inteiro (manifest) + começa no `initialChapterIndex` no
 * `initialTime`. Lida com:
 *
 *   - Carregamento dos Blobs MP3/TXT do IndexedDB.
 *   - Controles: play/pause, ±15s, velocidade, skip de capítulo.
 *   - Persistência de progresso (debounced) e velocidade global.
 *   - Media Session API: metadata + handlers para controles na lock screen
 *     do iPhone.
 *   - Avanço automático para o próximo capítulo ao terminar.
 *
 * Karaoke (highlight palavra-a-palavra) entra na Fase 5 — aqui o texto é
 * só rolante, sem sincronização visual.
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getAsset, getPrefs, getProgress, savePrefs, saveProgress } from "@/lib/storage";
import type { BookManifest, ChapterEntry, Prefs } from "@/lib/types";
import { DEFAULT_PREFS } from "@/lib/types";

const PLAYBACK_RATES = [0.75, 1.0, 1.25, 1.5, 2.0] as const;
const SEEK_SECONDS = 15;
const SAVE_PROGRESS_DEBOUNCE_MS = 1500;

type Props = {
  manifest: BookManifest;
};

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function chapterLabel(ch: ChapterEntry): string {
  if (ch.part && ch.total_parts) {
    return `${ch.title} (parte ${ch.part}/${ch.total_parts})`;
  }
  return ch.title;
}

export function Player({ manifest }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [textBody, setTextBody] = useState<string>("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  // Posição alvo a aplicar no audio quando ele estiver carregado.
  // null = nada pendente; 0 = começar do início.
  const [pendingSeek, setPendingSeek] = useState<number | null>(null);
  const [autoplayPending, setAutoplayPending] = useState(false);

  const chapter = manifest.chapters[chapterIndex];

  // Funções de controle estáveis (declaradas antes dos effects que dependem delas).

  const seekBy = useCallback((delta: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + delta));
  }, []);

  const goToChapter = useCallback(
    (idx: number, autoplay = false) => {
      if (idx < 0 || idx >= manifest.chapters.length) return;
      setPendingSeek(0);
      setAutoplayPending(autoplay);
      setChapterIndex(idx);
    },
    [manifest.chapters.length],
  );

  // ---- Hidrata progresso/prefs salvos no mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [progress, savedPrefs] = await Promise.all([
        getProgress(manifest.id),
        getPrefs(),
      ]);
      if (cancelled) return;
       
      setPrefs(savedPrefs);
      if (progress && progress.chapterIndex < manifest.chapters.length) {
         
        setChapterIndex(progress.chapterIndex);
         
        setPendingSeek(progress.currentTime);
      }
       
      setHydrated(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [manifest.id, manifest.chapters.length]);

  // ---- Carrega Blob do capítulo atual e cria Object URL.
  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    let revokeUrl: string | null = null;
    (async () => {
      try {
        const [mp3Blob, txtBlob] = await Promise.all([
          getAsset(manifest.id, chapter.mp3_path),
          getAsset(manifest.id, chapter.text_path),
        ]);
        if (cancelled) return;
        if (!mp3Blob) {
           
          setLoadError(`MP3 ausente: ${chapter.mp3_path}`);
          return;
        }
        const url = URL.createObjectURL(mp3Blob);
        revokeUrl = url;
         
        setLoadError(null);
         
        setAudioUrl(url);
        if (txtBlob) {
          const text = await txtBlob.text();
          if (cancelled) return;
           
          setTextBody(text);
        } else {
           
          setTextBody("");
        }
      } catch (err) {
        if (!cancelled) {
           
          setLoadError((err as Error).message);
        }
      }
    })();
    return () => {
      cancelled = true;
      if (revokeUrl) URL.revokeObjectURL(revokeUrl);
    };
  }, [hydrated, manifest.id, chapter.mp3_path, chapter.text_path]);

  // ---- Aplica taxa salva ao elemento de áudio.
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = prefs.playbackRate;
    }
  }, [prefs.playbackRate, audioUrl]);

  // ---- Persiste progresso com debounce.
  useEffect(() => {
    if (!hydrated) return;
    const handle = setTimeout(() => {
      saveProgress({
        bookId: manifest.id,
        chapterIndex,
        currentTime,
        lastPlayedAt: Date.now(),
      });
    }, SAVE_PROGRESS_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [hydrated, manifest.id, chapterIndex, currentTime]);

  // ---- Media Session API (lock-screen iOS, controles de hardware).
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: chapterLabel(chapter),
      artist: manifest.author ?? "ReaderFree",
      album: manifest.title,
    });
    const handlers: Array<[MediaSessionAction, () => void]> = [
      ["play", () => audioRef.current?.play()],
      ["pause", () => audioRef.current?.pause()],
      ["seekbackward", () => seekBy(-SEEK_SECONDS)],
      ["seekforward", () => seekBy(SEEK_SECONDS)],
      ["previoustrack", () => goToChapter(chapterIndex - 1)],
      ["nexttrack", () => goToChapter(chapterIndex + 1)],
    ];
    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        // Browser não suporta essa ação — ignora.
      }
    }
    return () => {
      for (const [action] of handlers) {
        try {
          navigator.mediaSession.setActionHandler(action, null);
        } catch {
          // ignore
        }
      }
    };
  }, [chapter, manifest.author, manifest.title, chapterIndex, seekBy, goToChapter]);

  // ---- Handlers do <audio> ----

  const handleLoadedMetadata = () => {
    const a = audioRef.current;
    if (!a) return;
    setDuration(a.duration);
    if (pendingSeek !== null) {
      a.currentTime = pendingSeek;
      setPendingSeek(null);
    }
    if (autoplayPending) {
      setAutoplayPending(false);
      a.play().catch(() => {
        // iOS bloqueia autoplay se não houve interação — silencia.
      });
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) setCurrentTime(audioRef.current.currentTime);
  };

  const handleEnded = () => {
    setIsPlaying(false);
    if (chapterIndex < manifest.chapters.length - 1) {
      goToChapter(chapterIndex + 1, true);
    }
  };

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play();
    else a.pause();
  };

  const seekTo = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (audioRef.current) audioRef.current.currentTime = Number(e.target.value);
  };

  const handleRateChange = async (rate: number) => {
    const next: Prefs = { ...prefs, playbackRate: rate };
    setPrefs(next);
    await savePrefs(next);
  };

  // ---- Render ----

  const totalChapters = manifest.chapters.length;
  const hasPrev = chapterIndex > 0;
  const hasNext = chapterIndex < totalChapters - 1;

  return (
    <main className="flex-1 flex flex-col h-screen">
      <header className="border-b border-neutral-800 px-4 py-3 flex items-center gap-3">
        <Link
          href="/"
          className="text-neutral-400 hover:text-neutral-100 text-sm"
          aria-label="Voltar à biblioteca"
        >
          ← Biblioteca
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-medium truncate">{manifest.title}</h1>
          <p className="text-xs text-neutral-500 truncate">
            {chapterLabel(chapter)} · {chapterIndex + 1}/{totalChapters}
          </p>
        </div>
      </header>

      <section className="flex-1 overflow-y-auto px-6 py-6">
        {loadError ? (
          <p className="text-red-300 text-sm">Erro: {loadError}</p>
        ) : (
          <article className="max-w-2xl mx-auto whitespace-pre-wrap leading-relaxed text-neutral-200">
            {textBody || (
              <span className="text-neutral-500 text-sm">Carregando texto...</span>
            )}
          </article>
        )}
      </section>

      <footer className="border-t border-neutral-800 px-4 py-3 flex flex-col gap-2 bg-neutral-950">
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={seekTo}
          className="w-full accent-amber-500"
          aria-label="Posição no áudio"
        />
        <div className="flex items-center justify-between text-xs text-neutral-400">
          <span>{formatTime(currentTime)}</span>
          <span>{formatTime(duration)}</span>
        </div>
        <div className="flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => goToChapter(chapterIndex - 1)}
            disabled={!hasPrev}
            className="p-2 text-neutral-300 disabled:opacity-30 hover:text-amber-400 transition"
            aria-label="Capítulo anterior"
          >
            ⏮
          </button>
          <button
            type="button"
            onClick={() => seekBy(-SEEK_SECONDS)}
            className="p-2 text-neutral-300 hover:text-amber-400 transition"
            aria-label={`Voltar ${SEEK_SECONDS}s`}
          >
            -{SEEK_SECONDS}s
          </button>
          <button
            type="button"
            onClick={togglePlay}
            disabled={!audioUrl}
            className="rounded-full w-14 h-14 bg-amber-500 text-neutral-950 text-2xl flex items-center justify-center disabled:opacity-30 hover:bg-amber-400 transition"
            aria-label={isPlaying ? "Pausar" : "Tocar"}
          >
            {isPlaying ? "⏸" : "▶"}
          </button>
          <button
            type="button"
            onClick={() => seekBy(SEEK_SECONDS)}
            className="p-2 text-neutral-300 hover:text-amber-400 transition"
            aria-label={`Avançar ${SEEK_SECONDS}s`}
          >
            +{SEEK_SECONDS}s
          </button>
          <button
            type="button"
            onClick={() => goToChapter(chapterIndex + 1)}
            disabled={!hasNext}
            className="p-2 text-neutral-300 disabled:opacity-30 hover:text-amber-400 transition"
            aria-label="Próximo capítulo"
          >
            ⏭
          </button>
        </div>
        <div className="flex items-center justify-center gap-2 text-xs">
          <span className="text-neutral-500">Velocidade:</span>
          {PLAYBACK_RATES.map((rate) => (
            <button
              key={rate}
              type="button"
              onClick={() => handleRateChange(rate)}
              className={
                prefs.playbackRate === rate
                  ? "px-2 py-1 rounded bg-amber-500 text-neutral-950 font-medium"
                  : "px-2 py-1 rounded text-neutral-400 hover:text-amber-400"
              }
            >
              {rate}x
            </button>
          ))}
        </div>
      </footer>

      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          preload="metadata"
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={handleTimeUpdate}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={handleEnded}
          className="hidden"
        />
      )}
    </main>
  );
}
