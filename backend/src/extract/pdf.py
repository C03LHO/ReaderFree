"""Extração de texto a partir de .pdf. Implementação na Fase 2."""
from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> list[dict]:
    """Retorna capítulos detectados via outline/bookmarks, ou um único capítulo."""
    raise NotImplementedError("Implementar na Fase 2.")
