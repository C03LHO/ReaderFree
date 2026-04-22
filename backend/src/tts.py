"""Wrapper do XTTS-v2 para síntese de voz pt-br. Fase 1."""
from __future__ import annotations

from pathlib import Path


def synthesize(
    chunks: list[str],
    output_wav: Path,
    voice: Path | None = None,
    language: str = "pt",
    device: str = "auto",
) -> None:
    """Sintetiza uma lista de chunks de texto em um único WAV concatenado."""
    raise NotImplementedError("Implementar na Fase 1.")
