"""Configuração global do pipeline.

Centraliza defaults aqui para evitar duplicação entre módulos.
"""
from __future__ import annotations

from dataclasses import dataclass


XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
WHISPER_MODEL = "large-v3"
DEFAULT_LANGUAGE = "pt"
DEFAULT_CHUNK_CHARS = 250
MP3_BITRATE = "96k"
AUDIO_SAMPLE_RATE = 24000


@dataclass(frozen=True)
class PipelineConfig:
    language: str = DEFAULT_LANGUAGE
    device: str = "auto"
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    mp3_bitrate: str = MP3_BITRATE
    xtts_model: str = XTTS_MODEL
    whisper_model: str = WHISPER_MODEL
