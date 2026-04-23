"""Alinhamento forçado texto↔áudio com WhisperX.

Dado o MP3 final + o texto original, retorna timestamps por palavra.
Usa o alinhador wav2vec2 do WhisperX com o texto conhecido como prior —
mais preciso que transcrição livre e preserva a grafia exata do original.

Duas implementações: `align` (real) e `align_mock` (distribuição uniforme).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config as cfg
from . import segment


_WORD_RE = re.compile(r"\S+")


def align(
    audio_path: Path,
    reference_text: str,
    language: str = "pt",
    device: str = "auto",
) -> list[dict]:
    """Executa forced alignment wav2vec2 do WhisperX no MP3 com texto conhecido.

    Retorna ``[{"word": str, "start": float, "end": float}, ...]`` em segundos,
    na ordem em que as palavras aparecem no reference_text.
    """
    # Lazy imports.
    import gc

    import whisperx

    resolved_device = cfg.resolve_device(device)
    audio = whisperx.load_audio(str(audio_path))
    audio_duration = len(audio) / 16000  # whisperx resampla p/ 16kHz

    sentences = segment.split_sentences(reference_text, "portuguese")
    if not sentences:
        return []

    # Distribui timestamps iniciais proporcionalmente. O alinhador wav2vec2
    # refina limites de palavra dentro de cada segmento.
    total_chars = sum(len(s) for s in sentences) or 1
    segments: list[dict] = []
    t = 0.0
    for s in sentences:
        share = audio_duration * (len(s) / total_chars)
        segments.append({"text": s, "start": t, "end": t + share})
        t += share

    align_model, metadata = whisperx.load_align_model(
        language_code=language, device=resolved_device
    )
    result = whisperx.align(
        segments,
        align_model,
        metadata,
        audio,
        resolved_device,
        return_char_alignments=False,
    )
    del align_model
    gc.collect()
    try:
        import torch

        if resolved_device == "cuda":
            torch.cuda.empty_cache()
    except ImportError:
        pass

    words: list[dict] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            if "start" in w and "end" in w and "word" in w:
                words.append(
                    {
                        "word": str(w["word"]).strip(),
                        "start": float(w["start"]),
                        "end": float(w["end"]),
                    }
                )
    return words


# =============================================================================
# MOCK MODE — distribui palavras uniformemente pela duração do áudio.
# =============================================================================


def align_mock(
    audio_path: Path,
    reference_text: str,
    language: str = "pt",
    device: str = "auto",
) -> list[dict]:
    """# MOCK MODE
    Distribui as palavras do reference_text ao longo da duração do áudio,
    proporcionalmente ao tamanho em caracteres de cada palavra. Não carrega
    WhisperX. Produz VTT sintético válido para o frontend testar sincronização.
    """
    from pydub import AudioSegment

    duration = len(AudioSegment.from_file(str(audio_path))) / 1000.0
    tokens = _WORD_RE.findall(reference_text)
    if not tokens:
        return []

    total_chars = sum(len(t) for t in tokens) or 1
    cues: list[dict] = []
    t = 0.0
    for tok in tokens:
        share = duration * (len(tok) / total_chars)
        cues.append(
            {
                "word": tok,
                "start": round(t, 3),
                "end": round(t + share, 3),
            }
        )
        t += share
    return cues
