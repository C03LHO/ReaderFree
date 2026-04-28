"""Testes de voices.list_speakers e da seleção de voz em tts._speaker_kwargs.

Não carrega coqui-tts real — usamos um stub do módulo `TTS.api` injetado
em sys.modules para simular a API sem precisar de torch/modelo.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from src.tts import _speaker_kwargs


# ============================================================================
# Stub do módulo TTS.api (compartilhado entre testes via fixture)
# ============================================================================

def _make_fake_tts_module(speakers: list[str]):
    """Cria um módulo fake `TTS.api` cujo `TTS(...)` retorna instância com .speakers."""
    fake_tts_module = types.ModuleType("TTS")
    fake_api_module = types.ModuleType("TTS.api")

    class FakeTTS:
        def __init__(self, model_name=None, progress_bar=False):
            self.speakers = list(speakers)

        def to(self, device):
            return self

        def tts(self, text, language, **kwargs):
            return [0.0] * 1000  # silêncio dummy

    fake_api_module.TTS = FakeTTS
    fake_tts_module.api = fake_api_module
    return fake_tts_module, fake_api_module


@pytest.fixture
def fake_tts_module(monkeypatch):
    """Injeta um TTS.api fake com 3 speakers conhecidos."""
    fake_tts, fake_api = _make_fake_tts_module(["Zoe", "Alice", "Bob"])
    monkeypatch.setitem(sys.modules, "TTS", fake_tts)
    monkeypatch.setitem(sys.modules, "TTS.api", fake_api)
    yield


# ============================================================================
# voices.list_speakers
# ============================================================================

def test_list_speakers_retorna_sorted(fake_tts_module):
    from src.voices import list_speakers
    assert list_speakers() == ["Alice", "Bob", "Zoe"]


def test_list_speakers_levanta_se_modelo_nao_expoe(monkeypatch):
    fake_tts, fake_api = _make_fake_tts_module([])
    monkeypatch.setitem(sys.modules, "TTS", fake_tts)
    monkeypatch.setitem(sys.modules, "TTS.api", fake_api)

    from src.voices import list_speakers
    with pytest.raises(RuntimeError, match="não expôs speakers"):
        list_speakers()


def test_list_speakers_levanta_import_error_sem_coqui(monkeypatch):
    """Se coqui-tts não está instalado, ImportError sobe sem virar RuntimeError."""
    # Garante que TTS não está em sys.modules.
    monkeypatch.delitem(sys.modules, "TTS", raising=False)
    monkeypatch.delitem(sys.modules, "TTS.api", raising=False)
    # Bloqueia o import.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "TTS.api" or name.startswith("TTS"):
            raise ImportError("simulando coqui-tts ausente")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from src.voices import list_speakers
    with pytest.raises(ImportError):
        list_speakers()


# ============================================================================
# tts._speaker_kwargs — precedência voice > speaker > fallback
# ============================================================================

class _FakeTTSInstance:
    def __init__(self, speakers: list[str]):
        self.speakers = list(speakers)


def test_speaker_kwargs_voice_tem_precedencia_sobre_speaker():
    tts = _FakeTTSInstance(["Alice", "Bob"])
    out = _speaker_kwargs(tts, voice=Path("/tmp/v.wav"), speaker="Alice")
    # voice ganha — speaker é ignorado.
    assert out == {"speaker_wav": "/tmp/v.wav"} or out == {"speaker_wav": str(Path("/tmp/v.wav"))}


def test_speaker_kwargs_speaker_nomeado_existente():
    tts = _FakeTTSInstance(["Alice", "Bob", "Zoe"])
    assert _speaker_kwargs(tts, voice=None, speaker="Bob") == {"speaker": "Bob"}


def test_speaker_kwargs_speaker_inexistente_levanta_com_lista():
    tts = _FakeTTSInstance(["Alice", "Bob", "Zoe"])
    with pytest.raises(RuntimeError) as exc:
        _speaker_kwargs(tts, voice=None, speaker="FooBar")
    msg = str(exc.value)
    assert "FooBar" in msg
    assert "não existe" in msg
    assert "Alice" in msg  # cita pelo menos um disponível
    assert "voices" in msg  # menciona o comando para listar


def test_speaker_kwargs_fallback_para_primeiro_speaker():
    tts = _FakeTTSInstance(["Alpha", "Beta"])
    assert _speaker_kwargs(tts, voice=None, speaker=None) == {"speaker": "Alpha"}


def test_speaker_kwargs_sem_speakers_e_sem_voice_levanta():
    tts = _FakeTTSInstance([])
    with pytest.raises(RuntimeError, match="não expôs speakers"):
        _speaker_kwargs(tts, voice=None, speaker=None)


def test_speaker_kwargs_lista_grande_trunca_no_erro():
    """Se há 50 speakers, mensagem de erro mostra só os primeiros 20."""
    tts = _FakeTTSInstance([f"Speaker_{i:02d}" for i in range(50)])
    with pytest.raises(RuntimeError) as exc:
        _speaker_kwargs(tts, voice=None, speaker="Inexistente")
    msg = str(exc.value)
    assert "30 mais" in msg  # 50 - 20 = 30 não mostrados
    # Speaker_19 (índice 19, nome com sufixo 19) está nos primeiros 20.
    assert "Speaker_19" in msg
    # Speaker_25 não aparece (já está nos 30 escondidos).
    assert "Speaker_25" not in msg
