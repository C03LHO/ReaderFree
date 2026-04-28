"""Listagem de vozes internas do XTTS-v2.

O modelo XTTS-v2 (`tts_models/multilingual/multi-dataset/xtts_v2`) vem com
dezenas de speakers pré-computados — é só pedir pelo nome em vez de gravar
uma amostra de voz. Este módulo expõe a lista; a CLI usa via `voices`.

Decisão da Fase 3 (redesenhada): voice cloning de arquivo (`--voice`)
continua funcionando como caminho alternativo, mas o fluxo recomendado
passa a ser `--speaker NOME` escolhendo entre os speakers internos.

Carrega o modelo lazy — chamar `list_speakers()` sem `[tts]` instalado
levanta ImportError com instrução de fix.
"""
from __future__ import annotations

from . import config as cfg


def list_speakers() -> list[str]:
    """Retorna a lista alfabética de speakers internos do XTTS-v2.

    Carrega o modelo na primeira chamada (~10–30s no disco quente, mais lento
    no primeiro download). Use `apply_model_cache_env` antes para redirecionar
    o cache se necessário — ver `pipeline.voices` no CLI.

    Raises:
        ImportError: `coqui-tts` não está instalado. Rode `pip install -e .[tts]`.
        RuntimeError: o modelo carregou mas não expôs `.speakers` (improvável
            com XTTS-v2; sinal de versão incompatível).
    """
    from TTS.api import TTS  # lazy

    tts = TTS(model_name=cfg.XTTS_MODEL, progress_bar=False)
    speakers = getattr(tts, "speakers", None)
    if not speakers:
        raise RuntimeError(
            f"Modelo {cfg.XTTS_MODEL} não expôs speakers internos. "
            f"Versão do coqui-tts pode estar incompatível."
        )
    return sorted(speakers)
