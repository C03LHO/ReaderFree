"""Empacotamento final: MP3 + VTT + book.json no diretório do livro. Fase 1."""
from __future__ import annotations

from pathlib import Path


def write_vtt(words: list[dict], output_path: Path) -> None:
    """Escreve um WebVTT com um cue por palavra."""
    raise NotImplementedError("Implementar na Fase 1.")


def write_book_json(metadata: dict, chapters: list[dict], output_dir: Path) -> None:
    """Escreve book.json com metadados e lista de capítulos."""
    raise NotImplementedError("Implementar na Fase 1.")
