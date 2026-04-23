"""Regressão do modo mock — trava o comportamento determinístico.

A fixture `bras_cubas_excerpt.expected.vtt` é o VTT canônico gerado a partir de
`bras_cubas_excerpt.txt` com `--mock`. Qualquer mudança em `tts.synthesize_mock`,
`align.align_mock`, `segment.*`, `package.write_vtt` ou `package.fmt_timestamp`
que alterar o output falha aqui — o desenvolvedor então compara e, se for
intencional, regenera a fixture.

Regenerar (se for mudança proposital):
    python pipeline.py build tests/fixtures/bras_cubas_excerpt.txt \\
        --output /tmp/out --mock --title "Brás Cubas Excerpt"
    cp /tmp/out/chapter_01.vtt tests/fixtures/bras_cubas_excerpt.expected.vtt
"""
from __future__ import annotations

from pathlib import Path

from src import align, package, segment, tts

FIXTURES = Path(__file__).parent / "fixtures"


def test_mock_vtt_bate_com_fixture(tmp_path):
    fixture_txt = FIXTURES / "bras_cubas_excerpt.txt"
    expected_vtt = FIXTURES / "bras_cubas_excerpt.expected.vtt"
    text = fixture_txt.read_text(encoding="utf-8").strip()

    sentences = segment.split_sentences(text, language="portuguese")
    chunks = segment.group_into_chunks(sentences, max_chars=250)

    wav_path = tmp_path / "ch.wav"
    mp3_path = tmp_path / "ch.mp3"
    vtt_path = tmp_path / "ch.vtt"

    tts.synthesize_mock(
        chunks=chunks,
        output_wav=wav_path,
        voice=None,
        language="pt",
        device="cpu",
        sample_rate=24000,
        progress_cb=None,
    )
    package.wav_to_mp3(wav_path, mp3_path, bitrate="96k")
    words = align.align_mock(mp3_path, text, language="pt", device="cpu")
    package.write_vtt(words, vtt_path)

    actual = vtt_path.read_text(encoding="utf-8")
    expected = expected_vtt.read_text(encoding="utf-8")
    assert actual == expected, (
        "Output do mock divergiu da fixture. "
        "Se a mudança for intencional, regenere conforme docstring."
    )
