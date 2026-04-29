"""Função pura de geração de audiobook (Fase 6.1+).

Refatorado a partir de `pipeline.py::build` para ser importável tanto pela
CLI quanto pelo worker do servidor (Fase 6). Não depende de Click/Rich —
toda comunicação de progresso é via callback (`on_progress`).

A função aceita um `cancel` callable que, se retornar True entre etapas
ou entre chunks do TTS, aborta a geração limpa (cleanup parcial, não tenta
remover arquivos já escritos).
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import align, chapter_range, chapter_split, config as cfg, package, sanitize, segment, tts


# ---- Eventos de progresso -------------------------------------------------

@dataclass(frozen=True)
class BuildProgress:
    """Evento de progresso emitido durante `build_book`.

    `phase` indica em qual etapa o build está. `current/total` formam a fração
    de progresso da etapa atual. `chapter_idx` (1-based) e `chapter_label`
    descrevem o capítulo em foco quando aplicável.
    """
    phase: str  # "extract" | "segment" | "tts" | "align" | "package"
    current: int
    total: int
    chapter_idx: Optional[int] = None
    chapter_label: Optional[str] = None
    message: Optional[str] = None


ProgressCb = Optional[Callable[[BuildProgress], None]]
CancelCb = Optional[Callable[[], bool]]


class BuildCancelled(Exception):
    """Levantada quando `cancel()` retorna True durante o build."""


# ---- API pública ----------------------------------------------------------

def build_book(
    input_path: Path,
    output_dir: Path,
    *,
    voice: Optional[Path] = None,
    speaker: Optional[str] = None,
    language: str = cfg.DEFAULT_LANGUAGE,
    device: str = "auto",
    chunk_chars: int = cfg.DEFAULT_CHUNK_CHARS,
    chapters_only: Optional[str] = None,
    auto_ocr: bool = False,
    include_auxiliary: bool = False,
    mock: bool = False,
    title: Optional[str] = None,
    author: Optional[str] = None,
    on_progress: ProgressCb = None,
    cancel: CancelCb = None,
) -> dict:
    """Gera um audiobook completo a partir de um arquivo TXT/PDF/EPUB.

    Esta é a função pura por trás de `pipeline.build` (CLI) e do worker do
    servidor da Fase 6.1. Não depende de Click/Rich — toda comunicação é
    via `on_progress` callback.

    Returns:
        dict com o conteúdo do `book.json`/`meta.json` gerado.

    Raises:
        BuildCancelled: se `cancel()` retornar True durante a execução.
        ValueError: input inválido (extensão não suportada, EPUB corrompido
            sem capítulos recuperáveis, PDF escaneado sem `auto_ocr`, etc.).
    """
    if not mock:
        paths = cfg.resolve_paths()
        cfg.apply_model_cache_env(paths)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Extração ---------------------------------------------------------
    _emit(on_progress, BuildProgress("extract", 0, 1, message=f"lendo {input_path.name}"))
    chapters = _extract(input_path, auto_ocr=auto_ocr, include_auxiliary=include_auxiliary)

    if chapters_only:
        selected = chapter_range.parse_chapter_range(chapters_only, total=len(chapters))
        chapters = [c for i, c in enumerate(chapters, start=1) if i in selected]
        if not chapters:
            raise ValueError(f"--chapters-only '{chapters_only}' não selecionou capítulos.")
    _check_cancel(cancel)

    # ---- Sanitização + split de capítulos longos -------------------------
    parts: list[tuple[int, dict]] = []
    for idx, chapter in enumerate(chapters, start=1):
        chapter["text"] = sanitize.sanitize_for_tts(chapter["text"])
        for part in chapter_split.split_chapter_if_needed(chapter):
            parts.append((idx, part))

    book_title = title or input_path.stem.replace("_", " ").strip()
    book_id = package.slugify(book_title) or uuid.uuid4().hex[:8]
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    synth_fn = tts.synthesize_mock if mock else tts.synthesize
    align_fn = align.align_mock if mock else align.align

    total_duration = 0.0
    chapter_entries: list[dict] = []
    n_parts_total = len(parts)

    for part_pos, (chapter_idx, part) in enumerate(parts, start=1):
        _check_cancel(cancel)
        ch_title: str = part["title"]
        ch_text: str = part["text"]
        is_split = "total_parts" in part

        if is_split:
            stem = f"chapter_{chapter_idx:02d}_part_{part['part']:02d}"
            label = f"Capítulo {chapter_idx:02d} ({part['part']}/{part['total_parts']}) — {ch_title}"
        else:
            stem = f"chapter_{chapter_idx:02d}"
            label = f"Capítulo {chapter_idx:02d} — {ch_title}"

        # ---- Segmentação --------------------------------------------------
        sentences = segment.split_sentences(ch_text, language="portuguese")
        chunks = segment.group_into_chunks(sentences, max_chars=chunk_chars)
        _emit(
            on_progress,
            BuildProgress(
                "segment", part_pos, n_parts_total,
                chapter_idx=chapter_idx, chapter_label=label,
                message=f"{len(sentences)} sentenças → {len(chunks)} chunks",
            ),
        )
        _check_cancel(cancel)

        wav_path = output_dir / f"{stem}.wav"
        mp3_path = output_dir / f"{stem}.mp3"
        vtt_path = output_dir / f"{stem}.vtt"
        txt_path = output_dir / f"{stem}.txt"

        # ---- TTS ---------------------------------------------------------
        def _tts_tick(done: int, total: int) -> None:
            _emit(
                on_progress,
                BuildProgress(
                    "tts", done, total,
                    chapter_idx=chapter_idx, chapter_label=label,
                ),
            )
            _check_cancel(cancel)

        synth_fn(
            chunks=chunks,
            output_wav=wav_path,
            voice=voice,
            speaker=speaker,
            language=language,
            device=device,
            sample_rate=cfg.TTS_SAMPLE_RATE,
            progress_cb=_tts_tick,
        )
        _check_cancel(cancel)

        # ---- WAV → MP3 + alinhamento + escrita ---------------------------
        _emit(on_progress, BuildProgress("package", part_pos, n_parts_total,
                                         chapter_idx=chapter_idx, chapter_label=label,
                                         message="WAV → MP3"))
        package.wav_to_mp3(wav_path, mp3_path, bitrate=cfg.MP3_BITRATE)
        wav_path.unlink(missing_ok=True)

        _emit(on_progress, BuildProgress("align", part_pos, n_parts_total,
                                         chapter_idx=chapter_idx, chapter_label=label))
        words = align_fn(mp3_path, ch_text, language=language, device=device)
        _check_cancel(cancel)

        package.write_vtt(words, vtt_path)
        package.write_txt(ch_text, txt_path)

        duration = package.audio_duration_seconds(mp3_path)
        total_duration += duration

        entry = {
            "id": f"{book_id}-{chapter_idx:02d}",
            "title": ch_title,
            "mp3_path": mp3_path.name,
            "vtt_path": vtt_path.name,
            "text_path": txt_path.name,
            "duration_seconds": round(duration, 3),
            "word_count": len(words),
        }
        if is_split:
            entry["part"] = part["part"]
            entry["total_parts"] = part["total_parts"]
        chapter_entries.append(entry)

    # ---- book.json (schema v1 — compatível com a Fase 1.5) ---------------
    package.write_book_json(
        book_id=book_id,
        title=book_title,
        author=author,
        created_at=created_at,
        duration_seconds=total_duration,
        chapters=chapter_entries,
        output_dir=output_dir,
        mock=mock,
    )
    return _read_book_json(output_dir)


# ---- Internals ------------------------------------------------------------

def _extract(input_path: Path, auto_ocr: bool, include_auxiliary: bool) -> list[dict]:
    """Dispatch por extensão. Espelha o `pipeline._extract` mas sem Click."""
    ext = input_path.suffix.lower()
    if ext == ".txt":
        from .extract import txt as extractor
        return extractor.extract(input_path)
    if ext == ".pdf":
        from .extract import pdf as extractor
        return extractor.extract(input_path, auto_ocr=auto_ocr)
    if ext == ".epub":
        from .extract import epub as extractor
        return extractor.extract(input_path, include_auxiliary=include_auxiliary)
    raise ValueError(f"Extensão não suportada: {ext}. Use .txt, .pdf ou .epub.")


def _emit(cb: ProgressCb, ev: BuildProgress) -> None:
    if cb is not None:
        cb(ev)


def _check_cancel(cb: CancelCb) -> None:
    if cb is not None and cb():
        raise BuildCancelled("build_book cancelado pelo caller")


def _read_book_json(output_dir: Path) -> dict:
    import json
    return json.loads((output_dir / "book.json").read_text(encoding="utf-8"))
