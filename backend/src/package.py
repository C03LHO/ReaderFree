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
    data = {
        "id": book_id,
        "title": title,
        "author": author,
        "created_at": created_at,
        "duration_seconds": round(float(duration_seconds), 3),
        "mock": mock,
        "chapters": chapters,
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
