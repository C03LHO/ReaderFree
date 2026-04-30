"""Extração de título/autor a partir do arquivo de entrada (Fase 6.2).

Cascata por extensão:
  - PDF: `pypdf.PdfReader.metadata` → fallback nome do arquivo limpo.
  - EPUB: `<dc:title>`, `<dc:creator>` no OPF via ebooklib.
  - TXT: nome do arquivo limpo (sem metadados nativos).

Sempre retorna `BookInfo`. Strings vazias ou ausentes viram `None`.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BookInfo:
    """Metadados básicos extraídos do arquivo de origem."""
    title: str
    author: Optional[str]


def extract_info(path: Path) -> BookInfo:
    """Detecta título/autor por extensão. Sempre retorna algo (fallback no
    nome do arquivo)."""
    ext = path.suffix.lower()
    title: Optional[str] = None
    author: Optional[str] = None

    if ext == ".pdf":
        title, author = _from_pdf(path)
    elif ext == ".epub":
        title, author = _from_epub(path)
    elif ext == ".txt":
        # TXT não tem metadata estruturada — só o nome do arquivo.
        pass
    # Outras extensões caem no fallback.

    if not title:
        title = _title_from_filename(path)
    return BookInfo(title=title, author=author or None)


# ---- PDF ------------------------------------------------------------------

def _from_pdf(path: Path) -> tuple[Optional[str], Optional[str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, None
    try:
        reader = PdfReader(str(path))
        meta = reader.metadata
    except Exception:
        return None, None
    if meta is None:
        return None, None
    title = _clean_str(getattr(meta, "title", None))
    author = _clean_str(getattr(meta, "author", None))
    return title, author


# ---- EPUB -----------------------------------------------------------------

def _from_epub(path: Path) -> tuple[Optional[str], Optional[str]]:
    try:
        from ebooklib import epub
    except ImportError:
        return None, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(str(path))
    except Exception:
        return None, None

    title = _first_dc_value(book, "title")
    author = _first_dc_value(book, "creator")
    return _clean_str(title), _clean_str(author)


def _first_dc_value(book, name: str) -> Optional[str]:
    """`book.get_metadata("DC", name)` retorna lista de tuplas
    `[(value, attrs)]`. Pegamos o primeiro value."""
    try:
        items = book.get_metadata("DC", name)
    except Exception:
        return None
    if not items:
        return None
    first = items[0]
    if isinstance(first, tuple) and first:
        return str(first[0])
    return None


# ---- Helpers --------------------------------------------------------------

def _clean_str(value) -> Optional[str]:
    """Normaliza: None/vazio → None, strip espaços extremos."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _title_from_filename(path: Path) -> str:
    """Deriva um título legível do nome do arquivo (sem extensão).

    Trata edge case onde `path.stem` ainda começa com ponto (ex:
    `.txt` → stem é `.txt`); strip de pontos das pontas.
    """
    stem = path.stem.replace("_", " ").replace("-", " ").strip(" .")
    return stem or "Sem título"
