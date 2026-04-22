"""Segmentação de texto em sentenças e agrupamento em chunks. Fase 1."""
from __future__ import annotations


def split_sentences(text: str, language: str = "portuguese") -> list[str]:
    """Divide texto em sentenças usando nltk.sent_tokenize."""
    raise NotImplementedError("Implementar na Fase 1.")


def group_into_chunks(sentences: list[str], max_chars: int) -> list[str]:
    """Agrupa sentenças em chunks de até `max_chars`, sem quebrar sentença no meio."""
    raise NotImplementedError("Implementar na Fase 1.")
