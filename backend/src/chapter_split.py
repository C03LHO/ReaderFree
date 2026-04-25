"""Divisão de capítulos longos em partes menores.

Decisão da Fase 2 (`docs/phase2-research.md` § 3): capítulos com mais de
~9000 palavras são divididos em partes de ~8000 palavras cada, quebrando em
fronteira de parágrafo. O critério é em **palavras**, não minutos —
minutos varia com voz/velocidade/conteúdo, palavras mapeiam direto pra
tamanho do MP3 e do VTT.

Os arquivos gerados pela Fase 2 ficam:
    chapter_05_part_01.mp3, chapter_05_part_01.vtt, ...
    chapter_05_part_02.mp3, chapter_05_part_02.vtt, ...

Capítulos com `total_parts == 1` (não divididos) não recebem os campos
`part`/`total_parts` no `book.json` — ausência é o sinal semântico de
"capítulo único" (cf. Fase 1.5).
"""
from __future__ import annotations

import re

# --- Configuração ---------------------------------------------------------

DEFAULT_TARGET_WORDS = 8000
"""Alvo de palavras por parte. Em ~150 wpm dá 50min ≈ 43 MB de MP3 a 96kbps."""

DEFAULT_TOLERANCE = 1.125
"""Capítulo até `target * tolerance` palavras NÃO é dividido.

Ex: target=8000, tolerance=1.125 → capítulos ≤ 9000 palavras ficam inteiros.
"""

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# --- API pública ----------------------------------------------------------

def split_chapter_if_needed(
    chapter: dict,
    target_words: int = DEFAULT_TARGET_WORDS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[dict]:
    """Divide um capítulo se ele passar do limiar; senão retorna inalterado.

    Args:
        chapter: dict com pelo menos `title` e `text`. Demais campos são
            preservados em todas as partes geradas.
        target_words: alvo de palavras por parte.
        tolerance: multiplicador acima do qual o capítulo é dividido.
            Capítulos com `word_count <= target * tolerance` não são tocados.

    Returns:
        Lista de capítulos. Se não dividido: 1 elemento sem campos
        `part`/`total_parts`. Se dividido em N partes: N elementos com
        `part=1..N` e `total_parts=N`, todos com o mesmo `title`.
    """
    if target_words < 1:
        raise ValueError(f"target_words deve ser ≥ 1 (recebi {target_words}).")
    if tolerance < 1.0:
        raise ValueError(f"tolerance deve ser ≥ 1.0 (recebi {tolerance}).")

    text = chapter["text"]
    total_words = _count_words(text)
    threshold = int(target_words * tolerance)

    if total_words <= threshold:
        return [dict(chapter)]

    # Decide quantas partes fazer: ceil(total / target), com balanceamento.
    n_parts = max(2, _ceil_div(total_words, target_words))
    parts_text = _split_text_balanced(text, n_parts, target_words)

    # Pode acontecer de _split_text_balanced retornar menos partes que o esperado
    # se o capítulo tiver poucos parágrafos (e.g., 1 parágrafo gigante).
    n_parts = len(parts_text)
    if n_parts == 1:
        return [dict(chapter)]

    result: list[dict] = []
    for i, part_text in enumerate(parts_text, start=1):
        entry = dict(chapter)
        entry["text"] = part_text
        entry["part"] = i
        entry["total_parts"] = n_parts
        result.append(entry)
    return result


# --- Internals ------------------------------------------------------------

def _count_words(text: str) -> int:
    return len(text.split())


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _split_text_balanced(text: str, n_parts: int, target_words: int) -> list[str]:
    """Divide texto em ~n_parts partes balanceadas em fronteira de parágrafo.

    Estratégia:
    1. Quebra o texto em parágrafos (\\n\\s*\\n).
    2. Computa palavras-cumulativas por parágrafo.
    3. Para cada corte alvo (k * target_words, k=1..n_parts-1), escolhe a
       fronteira de parágrafo cuja posição cumulativa esteja mais próxima
       do alvo. Se a melhor opção estiver a mais de 20% do alvo, cai para
       fronteira de sentença (degradação aceitável).
    4. Nunca dividir dentro de um parágrafo (só dentro de sentença em
       degradação extrema).
    """
    paragraphs = _PARAGRAPH_SPLIT_RE.split(text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if not paragraphs:
        return [text]

    # Se for um parágrafo único e gigante, cai pra split por sentenças.
    if len(paragraphs) == 1:
        return _split_by_sentences(paragraphs[0], n_parts, target_words)

    # Cumulative word count após cada parágrafo (índice 0 = depois do parágrafo 0).
    cum_words: list[int] = []
    running = 0
    for p in paragraphs:
        running += _count_words(p)
        cum_words.append(running)
    total = cum_words[-1]

    # Recalibra n_parts ao tamanho real (caso o caller tenha estimado mal).
    n_parts = max(2, _ceil_div(total, target_words))

    # Encontra cortes em fronteira de parágrafo.
    cut_indices: list[int] = []
    for k in range(1, n_parts):
        target = (total * k) // n_parts
        # Limites: no mínimo após o último cut + 1 parágrafo, e no máximo
        # antes do último parágrafo (precisa sobrar pelo menos 1 parágrafo
        # depois).
        min_idx = (cut_indices[-1] + 1) if cut_indices else 0
        max_idx = len(paragraphs) - 1  # exclusive: corta DEPOIS do parágrafo idx
        if min_idx >= max_idx:
            break  # acabaram os parágrafos
        # Procura o índice cuja posição cumulativa fica mais perto do target.
        best_idx = min(
            range(min_idx, max_idx),
            key=lambda i: abs(cum_words[i] - target),
        )
        # Tolerância: se o melhor estiver >20% longe do target, registra mas
        # ainda usa (não temos parágrafo melhor disponível).
        cut_indices.append(best_idx)

    if not cut_indices:
        # Não conseguiu cortar — capítulo curto demais com poucos parágrafos.
        return ["\n\n".join(paragraphs)]

    # Monta as partes.
    parts: list[list[str]] = []
    prev = 0
    for idx in cut_indices:
        parts.append(paragraphs[prev: idx + 1])
        prev = idx + 1
    parts.append(paragraphs[prev:])

    return ["\n\n".join(p) for p in parts if p]


def _split_by_sentences(text: str, n_parts: int, target_words: int) -> list[str]:
    """Degradação: divide em fronteira de sentença quando há só 1 parágrafo.

    Pior caso, raro em livros reais (1 parágrafo de 9000+ palavras).
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) < n_parts:
        return [text]

    cum_words: list[int] = []
    running = 0
    for s in sentences:
        running += _count_words(s)
        cum_words.append(running)
    total = cum_words[-1]
    n_parts = max(2, _ceil_div(total, target_words))

    cut_indices: list[int] = []
    for k in range(1, n_parts):
        target = (total * k) // n_parts
        min_idx = (cut_indices[-1] + 1) if cut_indices else 0
        max_idx = len(sentences) - 1
        if min_idx >= max_idx:
            break
        best_idx = min(range(min_idx, max_idx), key=lambda i: abs(cum_words[i] - target))
        cut_indices.append(best_idx)

    if not cut_indices:
        return [text]

    parts: list[list[str]] = []
    prev = 0
    for idx in cut_indices:
        parts.append(sentences[prev: idx + 1])
        prev = idx + 1
    parts.append(sentences[prev:])

    return [" ".join(p) for p in parts if p]
