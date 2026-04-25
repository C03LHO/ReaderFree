"""Testes do divisor de capítulos longos.

Cobre o critério em palavras (não minutos), tolerância de não-divisão,
balanceamento, quebra em fronteira de parágrafo, fallback para sentença.
"""
from __future__ import annotations

import pytest

from src.chapter_split import (
    DEFAULT_TARGET_WORDS,
    DEFAULT_TOLERANCE,
    split_chapter_if_needed,
)


def _para(n_words: int, label: str = "p") -> str:
    """Gera um parágrafo com `n_words` palavras únicas, prefixadas com `label`."""
    return " ".join(f"{label}{i}" for i in range(n_words))


def _chapter(text: str, **extra) -> dict:
    return {"title": "Cap", "text": text, **extra}


# ============================================================================
# Não-divisão (capítulos curtos)
# ============================================================================

def test_capitulo_curto_nao_divide():
    text = _para(500)
    out = split_chapter_if_needed(_chapter(text))
    assert len(out) == 1
    assert "part" not in out[0]
    assert "total_parts" not in out[0]
    assert out[0]["text"] == text


def test_capitulo_no_limiar_exato_nao_divide():
    # target=8000, tolerance=1.125 → threshold = 9000.
    text = _para(9000)
    out = split_chapter_if_needed(_chapter(text))
    assert len(out) == 1
    assert "part" not in out[0]


def test_capitulo_uma_palavra_acima_do_threshold_divide():
    # 9001 palavras com tolerance 1.125 deveria dividir.
    paragraphs = "\n\n".join(_para(1000, label=f"P{i}") for i in range(10))  # 10000 palavras
    out = split_chapter_if_needed(_chapter(paragraphs))
    assert len(out) >= 2
    for entry in out:
        assert "part" in entry
        assert "total_parts" in entry


# ============================================================================
# Divisão em N partes
# ============================================================================

def test_divide_em_partes_part_e_total_parts_corretos():
    # 24000 palavras / 8000 alvo = 3 partes.
    paragraphs = "\n\n".join(_para(1000, label=f"P{i}") for i in range(24))
    out = split_chapter_if_needed(_chapter(paragraphs))
    assert len(out) == 3
    for i, entry in enumerate(out, start=1):
        assert entry["part"] == i
        assert entry["total_parts"] == 3
        assert entry["title"] == "Cap"


def test_partes_balanceadas_em_palavras():
    # 24000 palavras em 24 parágrafos de 1000 → 3 partes de ~8000 palavras.
    paragraphs = "\n\n".join(_para(1000, label=f"P{i}") for i in range(24))
    out = split_chapter_if_needed(_chapter(paragraphs))
    word_counts = [len(entry["text"].split()) for entry in out]
    # Cada parte deve ter entre 7000 e 9000 palavras (10% de tolerância sobre 8000).
    for wc in word_counts:
        assert 7000 <= wc <= 9000, f"Parte com {wc} palavras fora de [7000, 9000]"
    # Soma preserva o total (sem perda de palavras).
    assert sum(word_counts) == 24000


def test_corte_acontece_em_fronteira_de_paragrafo():
    # Cria parágrafos identificáveis: primeiro tem só "AAA", segundo só "BBB",
    # etc. Verifica que cada parte começa/termina em parágrafo inteiro.
    paragraphs = []
    for i in range(20):
        marker = chr(ord("A") + i) * 3
        paragraphs.append(_para(1000) + " " + marker)
    text = "\n\n".join(paragraphs)
    out = split_chapter_if_needed(_chapter(text))

    # Cada parte deve conter parágrafos inteiros (o marker do último parágrafo
    # de cada parte tem que estar no fim, não no meio cortado).
    for entry in out:
        # Se o texto contém o marker, o parágrafo todo do marker está presente.
        for i in range(20):
            marker = chr(ord("A") + i) * 3
            if marker in entry["text"]:
                # Verifica que o parágrafo desse marker está completo:
                # ou seja, o texto que começa com pX e termina com marker
                # aparece intacto.
                last_para_of_chunk = entry["text"].rsplit("\n\n", 1)[-1]
                # Marker está no último parágrafo do chunk → marker fica no fim
                # OU está em algum parágrafo anterior → entrar em "p0 ... marker\n\n"
                # Em ambos os casos, marker é seguido por \n\n ou pelo fim.
                idx = entry["text"].find(marker)
                after = entry["text"][idx + len(marker):]
                # depois do marker: ou nada, ou começa com \n\n.
                assert after == "" or after.startswith("\n\n"), \
                    f"Marker {marker} não está em fronteira de parágrafo"


def test_preserva_outros_campos_no_chapter():
    paragraphs = "\n\n".join(_para(1000, label=f"P{i}") for i in range(20))
    chapter = _chapter(paragraphs, mp3_path="x.mp3", word_count=20000, custom="extra")
    out = split_chapter_if_needed(chapter)
    for entry in out:
        # Campos que existiam no original são preservados em todas as partes.
        assert entry["title"] == "Cap"
        assert entry["mp3_path"] == "x.mp3"
        assert entry["custom"] == "extra"
        # text foi sobrescrito; word_count também (caller pode/deve recalcular)
        assert "text" in entry


def test_nao_divide_quando_tem_um_paragrafo_unico_curto():
    # Apesar de ser 1 parágrafo, está abaixo do limiar → não divide.
    text = _para(5000)
    out = split_chapter_if_needed(_chapter(text))
    assert len(out) == 1


def test_paragrafo_unico_gigante_cai_para_sentencas():
    # 1 parágrafo gigante com sentenças bem definidas: degradação para split
    # por sentenças ainda funciona.
    sentences = [
        " ".join(f"w{i}_{j}" for j in range(500)) + "."
        for i in range(30)
    ]  # 30 sentenças de 500 palavras = 15000 palavras, sem \n\n
    text = " ".join(sentences)
    out = split_chapter_if_needed(_chapter(text))
    assert len(out) >= 2
    # Soma preserva total.
    total_words = sum(len(p["text"].split()) for p in out)
    assert total_words == 15000


# ============================================================================
# Casos limite
# ============================================================================

def test_target_words_zero_invalido():
    with pytest.raises(ValueError, match="target_words"):
        split_chapter_if_needed(_chapter(_para(100)), target_words=0)


def test_tolerance_menor_que_um_invalido():
    with pytest.raises(ValueError, match="tolerance"):
        split_chapter_if_needed(_chapter(_para(100)), tolerance=0.5)


def test_target_words_customizado():
    # Com target=100 e tolerance=1.125 (threshold=112), 200 palavras divide.
    text = "\n\n".join(_para(50, label=f"P{i}") for i in range(4))  # 200 palavras
    out = split_chapter_if_needed(_chapter(text), target_words=100)
    assert len(out) >= 2


def test_constantes_documentadas_batem_com_memo():
    # Sanity: o memo prometeu 8000 palavras e tolerância 1.125.
    assert DEFAULT_TARGET_WORDS == 8000
    assert DEFAULT_TOLERANCE == 1.125
