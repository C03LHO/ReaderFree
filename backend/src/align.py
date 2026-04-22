"""Alinhamento forçado texto↔áudio com WhisperX. Fase 1.

Dado um MP3 + o texto original, retorna timestamps por palavra.
"""
from __future__ import annotations

from pathlib import Path


def align(audio_path: Path, reference_text: str, language: str = "pt", device: str = "auto") -> list[dict]:
    """Retorna lista de {word, start, end} em segundos."""
    raise NotImplementedError("Implementar na Fase 1.")
