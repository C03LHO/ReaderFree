"""Segmentação de texto em sentenças e agrupamento em chunks.

XTTS-v2 trava com textos muito longos (limite prático ~400 chars), então
pré-quebramos em sentenças e reagrupamos sem quebrar sentenças ao meio.
"""
from __future__ import annotations

import re


_PUNKT_READY = False


def _ensure_punkt() -> None:
    """Garante que o tokenizador de sentenças do NLTK está baixado.

    Download é ~50KB (não é um modelo de IA, é uma tabela de regras).
    Idempotente: checa cache antes de baixar.
    """
    global _PUNKT_READY
    if _PUNKT_READY:
        return
    import nltk  # import local: nltk é leve mas evita custo no startup do CLI

    for resource in ("tokenizers/punkt_tab", "tokenizers/punkt"):
        try:
            nltk.data.find(resource)
            _PUNKT_READY = True
            return
        except LookupError:
            continue
    try:
        nltk.download("punkt_tab", quiet=True)
    except Exception:
        nltk.download("punkt", quiet=True)
    _PUNKT_READY = True


def split_sentences(text: str, language: str = "portuguese") -> list[str]:
    """Divide texto em sentenças, respeitando parágrafos.

    Linhas em branco duplas viram separador de parágrafos. Dentro de um
    parágrafo, newlines simples são colapsados em espaço.
    """
    if not text.strip():
        return []
    _ensure_punkt()
    from nltk.tokenize import sent_tokenize

    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s*\n\s*", " ", paragraph).strip()
        if not para:
            continue
        sentences.extend(s.strip() for s in sent_tokenize(para, language=language) if s.strip())
    return sentences


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Quebra uma sentença maior que max_chars em pedaços.

    Preferência de corte: após pontuação interna (, ; : —). Se nenhuma
    pontuação ajudar, quebra por palavras.
    """
    if len(sentence) <= max_chars:
        return [sentence]

    # Tenta cortar em pontuação interna
    parts = re.split(r"(?<=[,;:—–-])\s+", sentence)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if len(part) > max_chars:
            # Ainda muito longo: quebra por palavra
            if buf:
                chunks.append(buf.strip())
                buf = ""
            words = part.split()
            line = ""
            for w in words:
                if len(line) + len(w) + 1 > max_chars and line:
                    chunks.append(line.strip())
                    line = w
                else:
                    line = f"{line} {w}".strip()
            if line:
                buf = line
            continue
        if len(buf) + len(part) + 1 > max_chars and buf:
            chunks.append(buf.strip())
            buf = part
        else:
            buf = f"{buf} {part}".strip()
    if buf:
        chunks.append(buf.strip())
    return chunks


def group_into_chunks(sentences: list[str], max_chars: int) -> list[str]:
    """Agrupa sentenças em chunks de até max_chars sem quebrar no meio.

    Se uma sentença isolada ultrapassar max_chars, ela é subdividida por
    :func:`_split_long_sentence`.
    """
    if max_chars <= 0:
        raise ValueError("max_chars deve ser > 0")

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_sentence(sentence, max_chars))
            continue
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def word_count(text: str) -> int:
    """Conta palavras por whitespace (aproximação usada no stub de alinhamento)."""
    return len([w for w in re.split(r"\s+", text.strip()) if w])
