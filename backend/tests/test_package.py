"""Testes do escritor VTT e utilitários de empacotamento."""
from __future__ import annotations

import json

from src.package import (
    fmt_timestamp,
    slugify,
    write_book_json,
    write_vtt,
)


def test_fmt_timestamp_basico():
    assert fmt_timestamp(0) == "00:00:00.000"
    assert fmt_timestamp(1.234) == "00:00:01.234"
    assert fmt_timestamp(61.5) == "00:01:01.500"
    assert fmt_timestamp(3661.789) == "01:01:01.789"


def test_fmt_timestamp_negativo_vai_para_zero():
    assert fmt_timestamp(-0.5) == "00:00:00.000"


def test_write_vtt_gera_cue_por_palavra(tmp_path):
    words = [
        {"word": "Olá", "start": 0.24, "end": 0.38},
        {"word": "mundo", "start": 0.40, "end": 0.61},
    ]
    out = tmp_path / "ch.vtt"
    write_vtt(words, out)
    raw = out.read_text(encoding="utf-8")
    assert raw.startswith("WEBVTT\n")
    assert "00:00:00.240 --> 00:00:00.380" in raw
    assert "Olá" in raw
    assert "00:00:00.400 --> 00:00:00.610" in raw
    assert "mundo" in raw
    # Separa cues por linha em branco.
    assert "\n\nOlá\n" in raw or "\nOlá\n" in raw


def test_write_vtt_lista_vazia_so_header(tmp_path):
    out = tmp_path / "empty.vtt"
    write_vtt([], out)
    assert out.read_text(encoding="utf-8").strip() == "WEBVTT"


def test_write_book_json_estrutura(tmp_path):
    write_book_json(
        book_id="teste-livro",
        title="Teste Livro",
        author="Fulano",
        created_at="2026-04-22T00:00:00+00:00",
        duration_seconds=12.34,
        chapters=[
            {"id": "teste-livro-01", "title": "Cap 1", "mp3_path": "chapter_01.mp3",
             "vtt_path": "chapter_01.vtt", "text_path": "chapter_01.txt",
             "duration_seconds": 12.34, "word_count": 3},
        ],
        output_dir=tmp_path,
        mock=True,
    )
    data = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert data["id"] == "teste-livro"
    assert data["mock"] is True
    assert data["duration_seconds"] == 12.34
    assert len(data["chapters"]) == 1
    assert data["chapters"][0]["word_count"] == 3


def test_slugify_remove_acentos_e_normaliza():
    assert slugify("Memórias Póstumas de Brás Cubas") == "memorias-postumas-de-bras-cubas"
    assert slugify("  Oi   mundo!  ") == "oi-mundo"
    assert slugify("@#$%") == ""


def test_write_book_json_capitulos_divididos(tmp_path):
    """Fase 1.5: part/total_parts aparecem em capítulos divididos e somem em
    capítulos não-divididos, na mesma chamada."""
    chapters = [
        # Capítulo não-dividido — sem part/total_parts no dict.
        {
            "id": "livro-01",
            "title": "Prefácio",
            "mp3_path": "chapter_01.mp3",
            "vtt_path": "chapter_01.vtt",
            "text_path": "chapter_01.txt",
            "duration_seconds": 45.6,
            "word_count": 95,
        },
        # Capítulo dividido em 3 partes.
        {
            "id": "livro-02",
            "title": "Capítulo Longo",
            "mp3_path": "chapter_02_part_01.mp3",
            "vtt_path": "chapter_02_part_01.vtt",
            "text_path": "chapter_02_part_01.txt",
            "duration_seconds": 2700.0,
            "word_count": 8000,
            "part": 1,
            "total_parts": 3,
        },
        {
            "id": "livro-02",
            "title": "Capítulo Longo",
            "mp3_path": "chapter_02_part_02.mp3",
            "vtt_path": "chapter_02_part_02.vtt",
            "text_path": "chapter_02_part_02.txt",
            "duration_seconds": 2700.0,
            "word_count": 8000,
            "part": 2,
            "total_parts": 3,
        },
        {
            "id": "livro-02",
            "title": "Capítulo Longo",
            "mp3_path": "chapter_02_part_03.mp3",
            "vtt_path": "chapter_02_part_03.vtt",
            "text_path": "chapter_02_part_03.txt",
            "duration_seconds": 2700.0,
            "word_count": 8000,
            "part": 3,
            "total_parts": 3,
        },
        # Caller passou part=None explicitamente — deve sumir do JSON também.
        {
            "id": "livro-03",
            "title": "Posfácio",
            "mp3_path": "chapter_03.mp3",
            "vtt_path": "chapter_03.vtt",
            "text_path": "chapter_03.txt",
            "duration_seconds": 30.0,
            "word_count": 80,
            "part": None,
            "total_parts": None,
        },
    ]
    write_book_json(
        book_id="livro",
        title="Livro de Teste",
        author=None,
        created_at="2026-04-25T00:00:00+00:00",
        duration_seconds=8175.6,
        chapters=chapters,
        output_dir=tmp_path,
        mock=False,
    )
    data = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    chs = data["chapters"]
    assert len(chs) == 5

    # Capítulo não-dividido: ausência dos campos (não null).
    assert "part" not in chs[0]
    assert "total_parts" not in chs[0]

    # Três partes do capítulo longo: campos presentes com valores corretos.
    for i, expected_part in enumerate([1, 2, 3], start=1):
        assert chs[i]["part"] == expected_part
        assert chs[i]["total_parts"] == 3

    # Caller passou None explicitamente — também sumiu (não virou null no JSON).
    assert "part" not in chs[4]
    assert "total_parts" not in chs[4]
    raw = (tmp_path / "book.json").read_text(encoding="utf-8")
    assert "null" not in raw or raw.count("null") == 1  # só o author=None vira null


def test_write_book_json_part_sem_total_parts_e_descartado(tmp_path):
    """Se um dos dois faltar/for None, ambos são descartados — meio-termo é
    inválido."""
    write_book_json(
        book_id="x",
        title="X",
        author=None,
        created_at="2026-04-25T00:00:00+00:00",
        duration_seconds=10.0,
        chapters=[
            {
                "id": "x-01",
                "title": "Cap",
                "mp3_path": "chapter_01.mp3",
                "vtt_path": "chapter_01.vtt",
                "text_path": "chapter_01.txt",
                "duration_seconds": 10.0,
                "word_count": 5,
                "part": 1,
                # total_parts ausente
            },
        ],
        output_dir=tmp_path,
    )
    ch = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))["chapters"][0]
    assert "part" not in ch
    assert "total_parts" not in ch
