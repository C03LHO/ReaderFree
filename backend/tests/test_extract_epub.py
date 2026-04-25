"""Testes do extractor de EPUB.

Funções puras testadas direto. `extract` testado com EPUBs gerados em
fixture via ebooklib.
"""
from __future__ import annotations

import logging
import zipfile

import pytest
from ebooklib import epub

from src.extract.epub import (
    _decode_with_fallback,
    _filename_title,
    _is_linear,
    _parse_html,
    extract,
)


# ============================================================================
# Funções puras
# ============================================================================

def test_is_linear_string_no():
    assert _is_linear("no") is False
    assert _is_linear("NO") is False
    assert _is_linear("yes") is True
    assert _is_linear("") is True  # string vazia trata como linear


def test_is_linear_bool():
    assert _is_linear(True) is True
    assert _is_linear(False) is False


def test_is_linear_default_quando_none():
    # Spec EPUB: default é linear=yes quando atributo ausente.
    assert _is_linear(None) is True


def test_decode_with_fallback_utf8():
    assert _decode_with_fallback("olá".encode("utf-8")) == "olá"


def test_decode_with_fallback_cp1252():
    # 'olá' em cp1252 — utf-8 falha, cp1252 funciona.
    assert _decode_with_fallback("olá".encode("cp1252")) == "olá"


def test_decode_with_fallback_latin1_quase_sempre_funciona():
    # latin-1 aceita qualquer byte, então é o fallback final.
    assert _decode_with_fallback(b"\xe9") is not None


def test_filename_title_normaliza():
    assert _filename_title("chapter_05.xhtml") == "chapter 05"
    assert _filename_title("intro-do-livro.html") == "intro do livro"
    # Stem que vira só whitespace/punctuation cai em "Sem título".
    assert _filename_title("___.xhtml") == "Sem título"
    assert _filename_title("  .html") == "Sem título"


# ---- _parse_html -----------------------------------------------------------

def test_parse_html_extrai_titulo_de_h1():
    html = "<html><body><h1>Capítulo 1</h1><p>Texto.</p></body></html>"
    title, text = _parse_html(html, fallback_title="fb")
    assert title == "Capítulo 1"
    assert "Texto." in text


def test_parse_html_fallback_h2_quando_sem_h1():
    html = "<html><body><h2>Subcap</h2><p>Conteúdo.</p></body></html>"
    title, _ = _parse_html(html, fallback_title="fb")
    assert title == "Subcap"


def test_parse_html_fallback_title_quando_sem_heading():
    html = "<html><head><title>Livro</title></head><body><p>x.</p></body></html>"
    title, _ = _parse_html(html, fallback_title="fb")
    assert title == "Livro"


def test_parse_html_usa_fallback_quando_nada():
    html = "<html><body><p>só texto.</p></body></html>"
    title, _ = _parse_html(html, fallback_title="meu-fallback")
    assert title == "meu-fallback"


def test_parse_html_remove_script_e_style():
    html = """<html><body>
    <script>alert('xss')</script>
    <style>p { color: red; }</style>
    <h1>OK</h1>
    <p>Texto bom.</p>
    </body></html>"""
    _, text = _parse_html(html, fallback_title="fb")
    assert "alert" not in text
    assert "color" not in text
    assert "Texto bom." in text


def test_parse_html_remove_tabela_e_figure():
    html = """<html><body>
    <h1>X</h1>
    <p>Antes.</p>
    <table><tr><td>dados</td></tr></table>
    <figure><img/><figcaption>legenda</figcaption></figure>
    <p>Depois.</p>
    </body></html>"""
    _, text = _parse_html(html, fallback_title="fb")
    assert "dados" not in text
    assert "legenda" not in text
    assert "Antes." in text and "Depois." in text


def test_parse_html_remove_footnote_inline_via_sup():
    # <sup> é típico para link de nota de rodapé inline.
    html = """<html><body>
    <p>Frase com nota<sup>1</sup> no meio.</p>
    </body></html>"""
    _, text = _parse_html(html, fallback_title="fb")
    assert "1" not in text
    assert "Frase com nota no meio." in text or "Frase com nota  no meio." in text


def test_parse_html_remove_footnote_via_epub_type():
    html = """<html><body>
    <p>Texto principal.</p>
    <aside epub:type="footnote">Nota de rodapé inteira aqui.</aside>
    </body></html>"""
    _, text = _parse_html(html, fallback_title="fb")
    assert "rodapé" not in text
    assert "Texto principal." in text


def test_parse_html_paragrafos_separados_por_dupla_quebra():
    html = """<html><body>
    <p>Parágrafo um.</p>
    <p>Parágrafo dois.</p>
    <p>Parágrafo três.</p>
    </body></html>"""
    _, text = _parse_html(html, fallback_title="fb")
    assert text == "Parágrafo um.\n\nParágrafo dois.\n\nParágrafo três."


# ============================================================================
# extract() ponta-a-ponta com EPUBs gerados via ebooklib
# ============================================================================

def _make_chapter(title: str, content_html: str, file_name: str | None = None):
    fname = file_name or f"{title.lower().replace(' ', '_')}.xhtml"
    ch = epub.EpubHtml(title=title, file_name=fname, lang="pt")
    ch.content = content_html
    return ch


def _make_epub(tmp_path, chapters_with_linear: list[tuple[object, str]],
               book_title: str = "Test Book"):
    """`chapters_with_linear`: [(EpubHtml, "yes"|"no"|None), ...].

    None = sem atributo (default linear=yes).
    """
    book = epub.EpubBook()
    book.set_identifier("id-test")
    book.set_title(book_title)
    book.set_language("pt")
    spine: list = []
    for ch, linear in chapters_with_linear:
        book.add_item(ch)
        if linear == "no":
            spine.append((ch, "no"))
        else:
            spine.append(ch)
    book.toc = tuple(c for c, _ in chapters_with_linear)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    out = tmp_path / "book.epub"
    epub.write_epub(str(out), book)
    return out


def test_extract_epub_simples(tmp_path):
    c1 = _make_chapter(
        "Capítulo 1",
        "<html><body><h1>Capítulo 1</h1><p>Olá mundo.</p></body></html>",
    )
    out = _make_epub(tmp_path, [(c1, None)])
    chapters = extract(out)
    assert len(chapters) == 1
    assert chapters[0]["title"] == "Capítulo 1"
    assert "Olá mundo." in chapters[0]["text"]


def test_extract_epub_multiplos_capitulos_em_ordem(tmp_path):
    c1 = _make_chapter("A", "<html><body><h1>A</h1><p>texto a.</p></body></html>")
    c2 = _make_chapter("B", "<html><body><h1>B</h1><p>texto b.</p></body></html>")
    c3 = _make_chapter("C", "<html><body><h1>C</h1><p>texto c.</p></body></html>")
    out = _make_epub(tmp_path, [(c1, None), (c2, None), (c3, None)])
    chapters = extract(out)
    assert [c["title"] for c in chapters] == ["A", "B", "C"]


def test_extract_epub_pula_linear_no_por_default(tmp_path, caplog):
    main = _make_chapter("Main", "<html><body><h1>Main</h1><p>main.</p></body></html>")
    aux = _make_chapter("Apêndice A",
                        "<html><body><h1>Apêndice A</h1><p>apx.</p></body></html>")
    out = _make_epub(tmp_path, [(main, None), (aux, "no")])

    with caplog.at_level(logging.INFO):
        chapters = extract(out)

    assert len(chapters) == 1
    assert chapters[0]["title"] == "Main"
    assert any(
        "skipped" in rec.message and "Apêndice A" in rec.message
        for rec in caplog.records
    ), f"Esperava log de skip do apêndice. Logs: {[r.message for r in caplog.records]}"


def test_extract_epub_include_auxiliary_traz_linear_no(tmp_path):
    main = _make_chapter("Main", "<html><body><h1>Main</h1><p>main.</p></body></html>")
    aux = _make_chapter("Apêndice", "<html><body><h1>Apêndice</h1><p>apx.</p></body></html>")
    out = _make_epub(tmp_path, [(main, None), (aux, "no")])

    chapters = extract(out, include_auxiliary=True)
    assert len(chapters) == 2
    assert chapters[1]["title"] == "Apêndice"


def test_extract_epub_capitulo_vazio_e_pulado_sem_warning(tmp_path):
    c1 = _make_chapter("Real", "<html><body><h1>Real</h1><p>texto.</p></body></html>")
    # body com só whitespace — ebooklib aceita escrever, _parse_html retorna text vazio.
    c2 = _make_chapter("Vazio", "<html><body><p>   </p></body></html>")
    out = _make_epub(tmp_path, [(c1, None), (c2, None)])

    chapters = extract(out)
    assert len(chapters) == 1
    assert chapters[0]["title"] == "Real"


def test_extract_epub_recupera_html_quebrado(tmp_path):
    # HTML com tag não fechada — lxml em modo tolerante deve fechar sozinho.
    c1 = _make_chapter(
        "Quebrado",
        "<html><body><h1>Quebrado<p>texto sem fechar tags<p>outro</body></html>",
    )
    out = _make_epub(tmp_path, [(c1, None)])

    chapters = extract(out)
    assert len(chapters) == 1
    assert "texto sem fechar tags" in chapters[0]["text"]


def test_extract_epub_aborta_se_zero_capitulos_recuperaveis(tmp_path):
    # Todos os capítulos com body de só whitespace — produzem texto vazio
    # depois do parse e são pulados, resultando em chapters=[] e ValueError.
    c1 = _make_chapter("Vazio1", "<html><body><p>   </p></body></html>")
    c2 = _make_chapter("Vazio2", "<html><body><p>   </p></body></html>")
    out = _make_epub(tmp_path, [(c1, None), (c2, None)])

    with pytest.raises(ValueError, match="nenhum capítulo recuperável"):
        extract(out)


def test_extract_epub_remove_tabela_e_footnote_no_texto(tmp_path):
    c1 = _make_chapter(
        "X",
        """<html><body>
        <h1>X</h1>
        <p>Texto<sup>1</sup> normal.</p>
        <table><tr><td>tabela</td></tr></table>
        <p>Mais texto.</p>
        <aside epub:type="footnote">Nota completa.</aside>
        </body></html>""",
    )
    out = _make_epub(tmp_path, [(c1, None)])
    chapters = extract(out)
    text = chapters[0]["text"]
    assert "tabela" not in text
    assert "Nota completa" not in text
    assert "Texto" in text and "Mais texto." in text
