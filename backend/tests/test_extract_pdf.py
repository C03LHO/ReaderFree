"""Testes do extractor de PDF.

Funções puras (`_dehyphenate`, `_normalize_spaces`, `_split_by_heading_regex`)
testadas direto. `extract` testado com PDFs gerados em fixture via fpdf2.
"""
from __future__ import annotations

import pytest
from fpdf import FPDF

from src.extract.pdf import (
    MIN_CHARS_PER_PAGE,
    _dehyphenate,
    _normalize_spaces,
    _split_by_heading_regex,
    extract,
)


# ============================================================================
# Funções puras
# ============================================================================

def test_dehyphenate_junta_palavra_quebrada():
    assert _dehyphenate("recomen-\ndação") == "recomendação"


def test_dehyphenate_preserva_palavra_composta_inline():
    # bem-estar não está quebrado em linha — deve ficar intacto.
    assert _dehyphenate("ele tem bem-estar.") == "ele tem bem-estar."


def test_dehyphenate_multiplos_quebras():
    text = "uma sen-\ntença com hi-\nfens"
    assert _dehyphenate(text) == "uma sentença com hifens"


def test_normalize_spaces_junta_linhas_de_layout():
    # Quebras únicas viram espaço (PDF quebra linha por largura, não parágrafo).
    text = "linha um\nlinha dois\nlinha três"
    assert _normalize_spaces(text) == "linha um linha dois linha três"


def test_normalize_spaces_preserva_paragrafos():
    text = "parágrafo um.\n\nparágrafo dois."
    assert _normalize_spaces(text) == "parágrafo um.\n\nparágrafo dois."


def test_normalize_spaces_limita_quebras_triplas():
    text = "a\n\n\n\n\nb"
    assert _normalize_spaces(text) == "a\n\nb"


def test_normalize_spaces_colapsa_espacos_horizontais():
    assert _normalize_spaces("a    b\tc") == "a b c"


# ---- _split_by_heading_regex ------------------------------------------------

def test_heading_regex_detecta_capitulos_pt():
    # Conteúdo precisa ter >500 chars entre headings, senão é filtrado.
    body_a = "abcdef " * 100  # ~700 chars
    body_b = "ghijkl " * 100
    text = f"CAPÍTULO 1\n{body_a}\n\nCAPÍTULO 2\n{body_b}"
    chapters = _split_by_heading_regex(text)
    assert chapters is not None
    assert len(chapters) == 2
    assert "CAPÍTULO 1" in chapters[0]["title"]
    assert "CAPÍTULO 2" in chapters[1]["title"]


def test_heading_regex_filtra_headings_muito_proximos():
    # 2 headings com <500 chars de distância: o segundo é descartado
    # (provavelmente lixo de TOC ou cabeçalho de página).
    text = "CAPÍTULO 1\nbreve\n\nCAPÍTULO 2\nmais breve"
    chapters = _split_by_heading_regex(text)
    # Sobra só 1 (o filtro deixa o primeiro). 1 não dispara split → None.
    assert chapters is None


def test_heading_regex_um_so_match_retorna_none():
    text = "Capítulo 1\n" + ("texto " * 200)
    assert _split_by_heading_regex(text) is None


def test_heading_regex_padrao_numerado():
    body = "abcdef " * 100
    text = f"1. Introdução\n{body}\n\n2. Desenvolvimento\n{body}"
    chapters = _split_by_heading_regex(text)
    assert chapters is not None
    assert len(chapters) == 2


def test_heading_regex_sem_match_retorna_none():
    text = "texto contínuo sem nenhum heading reconhecível " * 50
    assert _split_by_heading_regex(text) is None


# ============================================================================
# extract() ponta-a-ponta com PDFs gerados via fpdf2
# ============================================================================

def _make_pdf(tmp_path, pages: list[str], outline: list[tuple[str, int]] | None = None):
    """Gera um PDF simples com texto. `outline` opcional: lista (titulo, page_idx)."""
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    for page_text in pages:
        pdf.add_page()
        # Quebra em linhas curtas — fpdf2 quebra automaticamente com multi_cell.
        pdf.multi_cell(0, 10, page_text)
    if outline:
        # fpdf2 expõe add_link/start_section. start_section adiciona ao outline.
        # Como já adicionamos as páginas, precisamos refazer com sections.
        pdf = FPDF()
        pdf.set_font("helvetica", size=12)
        for i, page_text in enumerate(pages):
            pdf.add_page()
            for title, page_idx in outline:
                if page_idx == i:
                    pdf.start_section(title)
            pdf.multi_cell(0, 10, page_text)
    out = tmp_path / "test.pdf"
    pdf.output(str(out))
    return out


def test_extract_pdf_simples_retorna_capitulo_unico(tmp_path):
    page = "Era uma vez um livro pequeno em PDF. " * 30  # ~1100 chars
    pdf_path = _make_pdf(tmp_path, [page, page])
    chapters = extract(pdf_path)
    assert len(chapters) == 1
    assert "Era uma vez" in chapters[0]["text"]


def test_extract_pdf_escaneado_aborta_com_instrucao(tmp_path):
    # PDF "vazio" — só páginas em branco, sem texto.
    pdf = FPDF()
    pdf.add_page()
    pdf.add_page()
    out = tmp_path / "scanned.pdf"
    pdf.output(str(out))

    with pytest.raises(ValueError, match="parece escaneado"):
        extract(out)


def test_extract_pdf_escaneado_mensagem_contem_solucoes(tmp_path):
    pdf = FPDF()
    pdf.add_page()
    out = tmp_path / "scan.pdf"
    pdf.output(str(out))

    with pytest.raises(ValueError) as excinfo:
        extract(out)
    msg = str(excinfo.value)
    assert "ocrmypdf" in msg
    assert "--auto-ocr" in msg


def test_extract_pdf_auto_ocr_sem_ocrmypdf_no_path(tmp_path, monkeypatch):
    """Se --auto-ocr passado mas ocrmypdf não está no PATH, erro claro."""
    pdf = FPDF()
    pdf.add_page()
    out = tmp_path / "x.pdf"
    pdf.output(str(out))

    # Garante que ocrmypdf não é encontrado.
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="ocrmypdf"):
        extract(out, auto_ocr=True)


def test_extract_pdf_capitulos_via_outline(tmp_path):
    # Texto longo o suficiente para passar do limiar chars/página.
    page1 = "Texto do primeiro capítulo. " * 50
    page2 = "Texto do segundo capítulo. " * 50
    page3 = "Texto do terceiro capítulo. " * 50
    pdf_path = _make_pdf(
        tmp_path,
        [page1, page2, page3],
        outline=[("Cap A", 0), ("Cap B", 1), ("Cap C", 2)],
    )
    chapters = extract(pdf_path)
    assert len(chapters) == 3
    assert chapters[0]["title"] == "Cap A"
    assert chapters[1]["title"] == "Cap B"
    assert chapters[2]["title"] == "Cap C"


def test_extract_pdf_min_chars_per_page_limiar_documentado():
    # Sanity: o limiar é o que o memo prometeu.
    assert MIN_CHARS_PER_PAGE == 100
