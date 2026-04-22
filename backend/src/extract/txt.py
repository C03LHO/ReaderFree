"""Extração de texto a partir de arquivos .txt. Implementação na Fase 1."""
from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> list[dict]:
    """Retorna uma lista de capítulos. Para .txt é sempre um único capítulo.

    Cada capítulo: {"title": str, "text": str}.
    """
    raise NotImplementedError("Implementar na Fase 1.")
