"""Testes de extração/geração de capa (`src/cover.py`)."""
from __future__ import annotations

import io
from pathlib import Path

from ebooklib import epub
from fpdf import FPDF
from PIL import Image

from src.cover import COVER_H, COVER_W, write_cover


# ============================================================================
# Output sempre é JPG 600x900
# ============================================================================

def test_write_cover_txt_gera_fallback_600x900(tmp_path):
    src = tmp_path / "input.txt"
    src.write_text("conteúdo", encoding="utf-8")
    out = tmp_path / "cover.jpg"
    rel = write_cover(src, out, title="Memórias Póstumas", author="Machado")
    assert rel == "cover.jpg"
    assert out.exists()
    img = Image.open(out)
    assert img.size == (COVER_W, COVER_H)
    assert img.format == "JPEG"


def test_write_cover_pdf_sem_imagem_cai_no_fallback(tmp_path):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(0, 10, text="só texto")
    src = tmp_path / "no_img.pdf"
    pdf.output(str(src))

    out = tmp_path / "cover.jpg"
    write_cover(src, out, title="Sem Imagem")
    img = Image.open(out)
    assert img.size == (COVER_W, COVER_H)


# ============================================================================
# EPUB com cover-image embutida
# ============================================================================

def _png_red(w: int = 800, h: int = 1200) -> bytes:
    """Gera um PNG vermelho de tamanho dado."""
    img = Image.new("RGB", (w, h), (200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _epub_with_cover(tmp_path: Path, cover_bytes: bytes) -> Path:
    book = epub.EpubBook()
    book.set_identifier("id-x")
    book.set_title("Livro Com Capa")
    book.add_author("Autor")
    book.set_language("pt")
    book.set_cover("cover.png", cover_bytes)
    c = epub.EpubHtml(title="Cap", file_name="c.xhtml", lang="pt")
    c.content = "<html><body><h1>x</h1><p>y</p></body></html>"
    book.add_item(c)
    book.toc = (c,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c]
    out = tmp_path / "livro.epub"
    epub.write_epub(str(out), book)
    return out


def test_write_cover_epub_extrai_cover_embutida(tmp_path):
    src = _epub_with_cover(tmp_path, _png_red())
    out = tmp_path / "cover.jpg"
    write_cover(src, out, title="ignorado")
    img = Image.open(out)
    assert img.size == (COVER_W, COVER_H)
    # Pixel central deve ser próximo do vermelho da capa original.
    px = img.getpixel((COVER_W // 2, COVER_H // 2))
    assert px[0] > 150 and px[1] < 80 and px[2] < 80, f"esperava vermelho, obtive {px}"


def test_write_cover_epub_sem_capa_cai_no_fallback(tmp_path):
    book = epub.EpubBook()
    book.set_identifier("id-y")
    book.set_title("Sem Capa")
    book.set_language("pt")
    c = epub.EpubHtml(title="C", file_name="c.xhtml", lang="pt")
    c.content = "<html><body><p>x</p></body></html>"
    book.add_item(c)
    book.toc = (c,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c]
    src = tmp_path / "sem_capa.epub"
    epub.write_epub(str(src), book)

    out = tmp_path / "cover.jpg"
    write_cover(src, out, title="Sem Capa")
    img = Image.open(out)
    assert img.size == (COVER_W, COVER_H)


# ============================================================================
# Fallback procedural — determinístico no título
# ============================================================================

def test_fallback_cor_deterministica_por_titulo(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("x", encoding="utf-8")

    out_a = tmp_path / "a.jpg"
    out_b = tmp_path / "b.jpg"
    write_cover(src, out_a, title="Mesmo Título")
    write_cover(src, out_b, title="Mesmo Título")
    # Comparação byte-a-byte por causa do JPEG (lossy mas determinístico).
    assert out_a.read_bytes() == out_b.read_bytes()


def test_fallback_titulos_diferentes_geram_capas_diferentes(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("x", encoding="utf-8")

    out_a = tmp_path / "a.jpg"
    out_b = tmp_path / "b.jpg"
    write_cover(src, out_a, title="Livro A")
    write_cover(src, out_b, title="Livro B")
    assert out_a.read_bytes() != out_b.read_bytes()
