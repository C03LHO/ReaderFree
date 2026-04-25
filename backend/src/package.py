"""Empacotamento final: MP3 + VTT + book.json no diretório do livro."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


def fmt_timestamp(seconds: float) -> str:
    """Formata segundos no layout WebVTT: HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - (hours * 3600) - (minutes * 60)
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def write_vtt(words: list[dict], output_path: Path) -> None:
    """Escreve um arquivo WebVTT com um cue por palavra.

    Layout:
        WEBVTT

        00:00:00.240 --> 00:00:00.380
        Olá

        00:00:00.400 --> 00:00:00.610
        mundo
    """
    lines: list[str] = ["WEBVTT", ""]
    for w in words:
        start = fmt_timestamp(float(w["start"]))
        end = fmt_timestamp(float(w["end"]))
        lines.append(f"{start} --> {end}")
        lines.append(str(w["word"]))
        lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_txt(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def _normalize_chapter_entry(chapter: dict) -> dict:
    """Limpa um dict de capítulo para serialização em `book.json`.

    Regra de `part`/`total_parts`: se o caller passa qualquer um dos dois como
    `None` (caso default de capítulo não-dividido), removemos os campos do
    dict — ausência é o sinal semântico, não `null` explícito. Se o caller
    passa ambos como ints válidos, preserva como veio.

    Outros campos passam adiante intactos.
    """
    cleaned = dict(chapter)
    part = cleaned.get("part")
    total = cleaned.get("total_parts")
    if part is None or total is None:
        cleaned.pop("part", None)
        cleaned.pop("total_parts", None)
    return cleaned


def write_book_json(
    book_id: str,
    title: str,
    author: str | None,
    created_at: str,
    duration_seconds: float,
    chapters: list[dict],
    output_dir: Path,
    mock: bool = False,
) -> None:
    """Serializa `book.json` com metadados do livro e lista de capítulos.

    Schema de cada capítulo (campos opcionais marcados com ?):
        id, title, mp3_path, vtt_path, text_path,
        duration_seconds, word_count,
        part?, total_parts?    # presentes só em capítulos divididos
    """
    data = {
        "id": book_id,
        "title": title,
        "author": author,
        "created_at": created_at,
        "duration_seconds": round(float(duration_seconds), 3),
        "mock": mock,
        "chapters": [_normalize_chapter_entry(c) for c in chapters],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def wav_to_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "96k") -> None:
    """Converte WAV para MP3 via pydub + ffmpeg."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(str(wav_path))
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(mp3_path), format="mp3", bitrate=bitrate)


def audio_duration_seconds(audio_path: Path) -> float:
    """Duração em segundos (funciona para WAV e MP3 via pydub/ffmpeg)."""
    from pydub import AudioSegment

    seg = AudioSegment.from_file(str(audio_path))
    return len(seg) / 1000.0


def slugify(text: str) -> str:
    """Slug ASCII-safe para IDs de livro/capítulo.

    "Memórias Póstumas" → "memorias-postumas".
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = re.sub(r"[^\w\s-]", "", ascii_only.lower())
    return re.sub(r"[\s_-]+", "-", ascii_only).strip("-")
