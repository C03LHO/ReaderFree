"""Testes do parser de --chapters-only.

Cobre os 10 casos definidos no memo (docs/phase2-research.md § 5).
"""
from __future__ import annotations

import pytest

from src.chapter_range import parse_chapter_range


# ---- Casos válidos ---------------------------------------------------------

def test_item_unico():
    assert parse_chapter_range("3", total=10) == {3}


def test_lista():
    assert parse_chapter_range("1,3,5", total=10) == {1, 3, 5}


def test_range():
    assert parse_chapter_range("1-3", total=10) == {1, 2, 3}


def test_combinacao_lista_e_range():
    assert parse_chapter_range("1,3,5-7,10", total=10) == {1, 3, 5, 6, 7, 10}


def test_sobreposicao_deduplicada():
    assert parse_chapter_range("1-3,2-4", total=10) == {1, 2, 3, 4}


def test_espacos_toleraveis():
    assert parse_chapter_range(" 1 , 3 - 5 ", total=10) == {1, 3, 4, 5}


def test_virgulas_extras_silenciosas():
    # "1,,3" não é elegante mas também não vale a pena rejeitar.
    assert parse_chapter_range("1,,3", total=10) == {1, 3}


def test_range_de_um_so():
    assert parse_chapter_range("5-5", total=10) == {5}


# ---- Casos inválidos -------------------------------------------------------

def test_range_invertido():
    with pytest.raises(ValueError, match="invertido"):
        parse_chapter_range("5-3", total=10)


def test_zero_invalido():
    with pytest.raises(ValueError, match="começam em 1"):
        parse_chapter_range("0", total=10)


def test_negativo_invalido():
    with pytest.raises(ValueError):
        parse_chapter_range("-1", total=10)


def test_lixo_nao_numerico():
    with pytest.raises(ValueError, match="não é um número"):
        parse_chapter_range("abc", total=10)


def test_range_com_letra():
    with pytest.raises(ValueError, match="não-numérico"):
        parse_chapter_range("1-a", total=10)


def test_fora_do_range_total():
    with pytest.raises(ValueError, match="fora do range"):
        parse_chapter_range("99", total=40)


def test_range_excede_total():
    with pytest.raises(ValueError, match="fora do range"):
        parse_chapter_range("38-42", total=40)


def test_spec_vazia():
    with pytest.raises(ValueError, match="vazio"):
        parse_chapter_range("", total=10)


def test_spec_so_espaco():
    with pytest.raises(ValueError, match="vazio"):
        parse_chapter_range("   ", total=10)


def test_total_zero():
    with pytest.raises(ValueError, match="sem capítulos"):
        parse_chapter_range("1", total=0)


def test_range_malformado_so_traco():
    with pytest.raises(ValueError, match="malformado"):
        parse_chapter_range("1-", total=10)


def test_range_malformado_dois_tracos():
    with pytest.raises(ValueError, match="malformado"):
        parse_chapter_range("1-2-3", total=10)
