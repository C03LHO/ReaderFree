"""Extração de texto a partir de .epub. Implementação na Fase 2."""
from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> list[dict]:
    """Retorna capítulos a partir do spine do EPUB, preservando a ordem."""
    raise NotImplementedError("Implementar na Fase 2.")
