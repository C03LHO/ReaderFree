"""Testes do extractor de TXT — normalização e titulação."""
from __future__ import annotations

from src.extract.txt import _normalize, extract


def test_normalize_colapsa_espacos():
    assert _normalize("olá    mundo") == "olá mundo"
    assert _normalize("olá\tmundo") == "olá mundo"


def test_normalize_unifica_crlf():
    assert _normalize("linha1\r\nlinha2") == "linha1\nlinha2"


def test_normalize_limita_quebras_duplas():
    assert _normalize("a\n\n\n\nb") == "a\n\nb"


def test_normalize_preserva_paragrafos():
    assert _normalize("parágrafo um.\n\nparágrafo dois.") == "parágrafo um.\n\nparágrafo dois."


def test_extract_retorna_um_capitulo_com_titulo_a_partir_do_stem(tmp_path):
    f = tmp_path / "meu_livro-teste.txt"
    f.write_text("Olá mundo.", encoding="utf-8")
    result = extract(f)
    assert len(result) == 1
    assert result[0]["text"] == "Olá mundo."
    assert result[0]["title"] == "meu livro teste"
