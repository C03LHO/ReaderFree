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
