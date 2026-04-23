"""Wrapper do XTTS-v2 para síntese de voz pt-br.

Duas implementações: `synthesize` (real) e `synthesize_mock` (silêncio).
O CLI escolhe qual usar via a flag --mock.

IMPORTANTE: todas as importações pesadas (torch, TTS) são *lazy* — só carregam
quando a função real é chamada. Isso mantém o startup do CLI rápido e permite
rodar --mock em máquinas sem torch/TTS instalados.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from . import config as cfg


ProgressCb = Optional[Callable[[int, int], None]]


def synthesize(
    chunks: list[str],
    output_wav: Path,
    voice: Path | None = None,
    language: str = "pt",
    device: str = "auto",
    sample_rate: int = cfg.TTS_SAMPLE_RATE,
    progress_cb: ProgressCb = None,
) -> None:
    """Sintetiza chunks com XTTS-v2, concatena e grava em output_wav (WAV 24kHz mono).

    Entre chunks é inserida uma pequena pausa de 200ms para fluidez.
    """
    # Lazy imports — só carregam aqui.
    import numpy as np
    import soundfile as sf
    from TTS.api import TTS  # coqui-tts

    resolved_device = cfg.resolve_device(device)
    tts = TTS(model_name=cfg.XTTS_MODEL, progress_bar=False).to(resolved_device)

    pause = np.zeros(int(sample_rate * 0.2), dtype=np.float32)
    speaker_kwargs = _speaker_kwargs(tts, voice)

    parts: list[np.ndarray] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        try:
            wav = tts.tts(text=chunk, language=language, **speaker_kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"XTTS falhou no chunk {i + 1}/{total}: {exc}\n"
                f"Chunk: {chunk[:80]!r}..."
            ) from exc
        parts.append(np.asarray(wav, dtype=np.float32))
        parts.append(pause.copy())
        if progress_cb:
            progress_cb(i + 1, total)

    full = np.concatenate(parts[:-1]) if parts else np.zeros(sample_rate, dtype=np.float32)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_wav), full, sample_rate)


def _speaker_kwargs(tts, voice: Path | None) -> dict:
    """Se --voice foi passado, usa voice cloning. Senão, usa speaker pré-computado."""
    if voice is not None:
        return {"speaker_wav": str(voice)}
    speakers = getattr(tts, "speakers", None)
    if speakers:
        return {"speaker": speakers[0]}
    raise RuntimeError(
        "XTTS-v2 não expôs speakers pré-computados; passe --voice com um WAV de referência."
    )


# =============================================================================
# MOCK MODE — não carrega torch/TTS, gera silêncio determinístico.
# =============================================================================


def synthesize_mock(
    chunks: list[str],
    output_wav: Path,
    voice: Path | None = None,
    language: str = "pt",
    device: str = "auto",
    sample_rate: int = cfg.TTS_SAMPLE_RATE,
    progress_cb: ProgressCb = None,
) -> None:
    """# MOCK MODE
    Gera silêncio com duração proporcional ao texto (~15 chars/segundo para
    pt-br). Não carrega modelos. Usado para validar o pipeline de dados em
    máquinas sem GPU ou sem `coqui-tts` instalado.
    """
    import numpy as np
    import soundfile as sf

    CHARS_PER_SECOND = 15.0
    PAUSE_SECONDS = 0.2
    pause = np.zeros(int(sample_rate * PAUSE_SECONDS), dtype=np.float32)

    parts: list[np.ndarray] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        duration = max(0.5, len(chunk) / CHARS_PER_SECOND)
        parts.append(np.zeros(int(duration * sample_rate), dtype=np.float32))
        parts.append(pause.copy())
        if progress_cb:
            progress_cb(i + 1, total)

    full = np.concatenate(parts[:-1]) if parts else np.zeros(sample_rate, dtype=np.float32)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_wav), full, sample_rate)
