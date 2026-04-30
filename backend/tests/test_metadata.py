"""Testes de extração de título/autor (`src/metadata.py`)."""
from __future__ import annotations

from pathlib import Path

from ebooklib import epub
from fpdf import FPDF

from src.metadata import BookInfo, _title_from_filename, extract_info


# ============================================================================
# _title_from_filename
# ============================================================================

def test_title_from_filename_normaliza(tmp_path):
    assert _title_from_filename(tmp_path / "memoria_postuma.txt") == "memoria postuma"
    assert _title_from_filename(tmp_path / "Bras-Cubas.epub") == "Bras Cubas"


def test_title_from_filename_so_simbolos(tmp_path):
    # Stem que vira whitespace/punct pura (raro mas possível) cai em fallback.
    assert _title_from_filename(tmp_path / "___.txt") == "Sem título"
    assert _title_from_filename(tmp_path / "  -- .txt") == "Sem título"


# ============================================================================
# TXT
# ============================================================================

def test_extract_info_txt_usa_filename(tmp_path):
    f = tmp_path / "memorias_postumas_de_bras_cubas.txt"
    f.write_text("Olá", encoding="utf-8")
    info = extract_info(f)
    assert info.title == "memorias postumas de bras cubas"
    assert info.author is None


# ============================================================================
# PDF
# ============================================================================

def test_extract_info_pdf_com_metadata(tmp_path):
    pdf = FPDF()
    pdf.set_title("Meu Livro PDF")
    pdf.set_author("Joaquim Maria")
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(0, 10, text="conteúdo")
    out = tmp_path / "livro.pdf"
    pdf.output(str(out))

    info = extract_info(out)
    assert info.title == "Meu Livro PDF"
    assert info.author == "Joaquim Maria"


def test_extract_info_pdf_sem_metadata_cai_no_filename(tmp_path):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(0, 10, text="x")
    out = tmp_path / "fallback_aqui.pdf"
    pdf.output(str(out))

    info = extract_info(out)
    assert info.title == "fallback aqui"
    assert info.author is None


# ============================================================================
# EPUB
# ============================================================================

def _make_epub(tmp_path: Path, title: str, author: str | None) -> Path:
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    if author is not None:
        book.add_author(author)
    book.set_language("pt")
    c1 = epub.EpubHtml(title="Cap1", file_name="c1.xhtml", lang="pt")
    c1.content = "<html><body><h1>X</h1><p>texto</p></body></html>"
    book.add_item(c1)
    book.toc = (c1,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c1]
    out = tmp_path / "livro.epub"
    epub.write_epub(str(out), book)
    return out


def test_extract_info_epub_com_titulo_e_autor(tmp_path):
    p = _make_epub(tmp_path, "Memórias Póstumas", "Machado de Assis")
    info = extract_info(p)
    assert info.title == "Memórias Póstumas"
    assert info.author == "Machado de Assis"


def test_extract_info_epub_sem_autor(tmp_path):
    p = _make_epub(tmp_path, "Só Título", None)
    info = extract_info(p)
    assert info.title == "Só Título"
    assert info.author is None


# ============================================================================
# Robustez
# ============================================================================

def test_extract_info_arquivo_inexistente_cai_no_filename(tmp_path):
    p = tmp_path / "nao_existe.pdf"
    info = extract_info(p)
    assert info.title == "nao existe"
    assert info.author is None


def test_extract_info_extensao_estranha(tmp_path):
    p = tmp_path / "qualquer.docx"
    p.write_text("x", encoding="utf-8")
    info = extract_info(p)
    assert info.title == "qualquer"
    assert isinstance(info, BookInfo)
