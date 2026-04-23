"""Extração de texto a partir de arquivos .txt."""
from __future__ import annotations

import re
from pathlib import Path


def _normalize(text: str) -> str:
    """Normaliza espaços e quebras de linha preservando parágrafos.

    - Unifica CRLF/CR para LF.
    - Colapsa espaços/tabs repetidos num único espaço.
    - Mantém parágrafos (linhas em branco duplas) mas limita a duas quebras
      seguidas para evitar pausas artificiais gigantes no TTS.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(path: Path) -> list[dict]:
    """Lê um .txt UTF-8 e retorna uma lista com um único capítulo.

    Retorno: ``[{"title": str, "text": str}]``.

    Para arquivos com mais de um capítulo (marcadores tipo "Capítulo 1"),
    mantemos como capítulo único na Fase 1 — detecção de capítulos em TXT
    é heurística e pode ser adicionada depois se necessário.
    """
    raw = path.read_text(encoding="utf-8")
    text = _normalize(raw)
    title = path.stem.replace("_", " ").replace("-", " ").strip() or "Sem título"
    return [{"title": title, "text": text}]
