"""Testes do segmentador. Não dependem de torch/TTS/whisperx."""
from __future__ import annotations

from src.segment import group_into_chunks, split_sentences, word_count


def test_split_sentences_pt_basico():
    text = "Olá, mundo. Este é um teste. Como você está?"
    sentences = split_sentences(text)
    assert sentences == ["Olá, mundo.", "Este é um teste.", "Como você está?"]


def test_split_sentences_respeita_paragrafos():
    text = "Primeira frase do parágrafo 1. Segunda frase.\n\nParágrafo 2 aqui."
    sentences = split_sentences(text)
    assert sentences == [
        "Primeira frase do parágrafo 1.",
        "Segunda frase.",
        "Parágrafo 2 aqui.",
    ]


def test_split_sentences_texto_vazio():
    assert split_sentences("") == []
    assert split_sentences("   \n\n  ") == []


def test_group_into_chunks_agrupa_ate_limite():
    sentences = ["Um.", "Dois.", "Três.", "Quatro."]
    chunks = group_into_chunks(sentences, max_chars=10)
    # "Um. Dois." = 9 chars <= 10, "Três." = 5 chars, "Quatro." = 7 chars
    assert chunks == ["Um. Dois.", "Três.", "Quatro."]


def test_group_into_chunks_nao_quebra_sentenca_dentro_do_limite():
    sentences = ["Uma sentença de trinta chars ok.", "Outra."]  # 32 + 1 + 6 = 39
    chunks = group_into_chunks(sentences, max_chars=35)
    # max_chars=35: juntas (39) ultrapassam, então saem separadas, sem quebra.
    assert len(chunks) == 2
    assert chunks[0] == "Uma sentença de trinta chars ok."
    assert chunks[1] == "Outra."


def test_group_into_chunks_quebra_sentenca_gigante():
    long_sent = "Parte um, parte dois, parte três, parte quatro, parte cinco."
    chunks = group_into_chunks([long_sent], max_chars=20)
    assert all(len(c) <= 20 for c in chunks), f"Algum chunk excede 20 chars: {chunks}"
    # Reconstrói aproximadamente o texto original (sem perder palavras)
    reconstituted = " ".join(chunks)
    for word in ["um", "dois", "três", "quatro", "cinco"]:
        assert word in reconstituted


def test_group_into_chunks_max_chars_invalido():
    import pytest

    with pytest.raises(ValueError):
        group_into_chunks(["abc"], max_chars=0)


def test_word_count():
    assert word_count("Olá mundo bonito") == 3
    assert word_count("  uma   palavra  ") == 2
    assert word_count("") == 0
