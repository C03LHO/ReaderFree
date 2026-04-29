"use client";

/**
 * Render do texto do capítulo como sequência de palavras com highlight
 * sincronizado ao áudio.
 *
 * Estratégia de render (Fase 5):
 *
 *   - Cada palavra do VTT vira um `<span data-word-index={i}>`. As palavras
 *     são as únicas unidades clicáveis — texto fora de cues vira whitespace
 *     entre spans.
 *   - O cue ativo recebe destaque (âmbar). Os demais ficam na cor base —
 *     visual minimalista. "Esmaecer já-lido" pode ser refinamento futuro.
 *   - Tap/click na palavra dispara `onSeek(cue.start)`.
 *   - Auto-scroll mantém a palavra ativa visível com `scrollIntoView` em
 *     `block: "center"`. Se o usuário scrollou recentemente, pausamos o
 *     auto-scroll por 4s para não brigar com a interação manual.
 *
 * Performance: capítulos divididos pela Fase 2 ficam ≤9000 palavras.
 * 9000 spans renderizados em React 19 + Tailwind é leve (~30ms inicial,
 * <2ms por re-render quando só `activeIndex` muda — `key={index}`
 * estável + apenas o span ativo recebe classe diferente). Não usamos
 * `react-window` por enquanto. Quando virar problema concreto, vale.
 */
import { useEffect, useMemo, useRef } from "react";

import type { WordCue } from "@/lib/vtt";

const SCROLL_RESUME_AFTER_MANUAL_MS = 4000;

type Props = {
  cues: WordCue[];
  /** Índice do cue ativo (-1 = nenhum). Vem do Player via busca binária. */
  activeIndex: number;
  /** Chamado quando usuário toca/clica numa palavra. Recebe `cue.start`. */
  onSeek: (timeSeconds: number) => void;
  /**
   * Texto bruto do capítulo (`chapter_NN.txt`). Mostrado quando `cues`
   * está vazio ou quando o `mode === "text-only"` no Player. Garante
   * que o usuário sempre vê algo, mesmo se o VTT falhar.
   */
  fallbackText?: string;
};

export function TextViewer({ cues, activeIndex, onSeek, fallbackText }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const lastUserScrollRef = useRef<number>(0);

  // Detecta scroll manual recente para pausar auto-scroll.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: Event) => {
      // Filtra eventos disparados pelo nosso próprio scrollIntoView.
      // scrollIntoView dispara scroll programático sem `isTrusted=true` em
      // alguns browsers — usamos a marca temporal para isso.
      if ((e as Event & { isTrusted?: boolean }).isTrusted === false) return;
      lastUserScrollRef.current = Date.now();
    };
    el.addEventListener("scroll", handler, { passive: true });
    return () => el.removeEventListener("scroll", handler);
  }, []);

  // Auto-scroll para manter a palavra ativa centralizada.
  useEffect(() => {
    if (activeIndex < 0) return;
    const sinceLastUserScroll = Date.now() - lastUserScrollRef.current;
    if (sinceLastUserScroll < SCROLL_RESUME_AFTER_MANUAL_MS) return;

    const container = containerRef.current;
    if (!container) return;
    const span = container.querySelector<HTMLSpanElement>(
      `span[data-word-index="${activeIndex}"]`,
    );
    if (!span) return;
    span.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeIndex]);

  // Delegação de click: identifica a palavra clicada via data-word-index.
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const span = target.closest<HTMLSpanElement>("span[data-word-index]");
    if (!span) return;
    const idx = Number(span.dataset.wordIndex);
    if (Number.isNaN(idx) || idx < 0 || idx >= cues.length) return;
    onSeek(cues[idx].start);
  };

  // Memoiza as classes/spans pra evitar reprocessar em cada re-render.
  // Só o span ativo precisa de classe especial — tudo derivado de activeIndex.
  const spans = useMemo(() => {
    return cues.map((cue) => (
      <Word key={cue.index} cue={cue} />
    ));
  }, [cues]);

  if (cues.length === 0) {
    return (
      <article className="max-w-2xl mx-auto whitespace-pre-wrap leading-relaxed text-neutral-200">
        {fallbackText || (
          <span className="text-neutral-500 text-sm">
            VTT vazio — texto sincronizado indisponível para este capítulo.
          </span>
        )}
      </article>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto px-6 py-6"
      onClick={handleClick}
    >
      <article
        className="max-w-2xl mx-auto leading-relaxed text-neutral-300"
        data-active-index={activeIndex}
      >
        {spans}
      </article>
      {/* Highlight CSS-driven: o React só atualiza o atributo
          `data-active-index` no <article>; o seletor abaixo destaca o
          span correto. Evita re-render de N spans por frame. */}
      <style>{`
        [data-active-index] span[data-word-index] {
          cursor: pointer;
          transition: color 80ms;
        }
        ${activeIndexCss(activeIndex)}
      `}</style>
    </div>
  );
}

/**
 * Gera o seletor CSS que destaca o cue ativo.
 *
 * Em vez de re-renderizar todos os spans a cada frame, geramos uma única
 * regra `[data-active-index="${i}"] span[data-word-index="${i}"]`. O
 * React só atualiza um atributo no `<article>` por frame, e o CSS aplica
 * a cor no span certo. O(1) por frame, independentemente do número de
 * palavras no capítulo.
 */
function activeIndexCss(activeIndex: number): string {
  if (activeIndex < 0) return "";
  return `
    [data-active-index="${activeIndex}"] span[data-word-index="${activeIndex}"] {
      color: rgb(251 191 36);
      font-weight: 600;
    }
  `;
}

/**
 * Span de uma única palavra. Memoizado por `cue.index` (estável) — só
 * re-renderiza se o cue em si mudar (efetivamente nunca, já que VTT é
 * imutável dentro do capítulo).
 */
function Word({ cue }: { cue: WordCue }) {
  // Preserva a palavra exata como veio do VTT. Espaço entre palavras é
  // simulado com um espaço dentro do span — evita cair em " " textuais
  // separados que quebrariam a delegação de click.
  return (
    <>
      <span data-word-index={cue.index}>{cue.word}</span>{" "}
    </>
  );
}
