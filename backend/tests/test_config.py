"""Testes de config.py — resolução de paths + env vars de cache de modelos.

Não dependem de torch/TTS/whisperx. Usam monkeypatch para isolar env/filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import config as cfg


@pytest.fixture
def clean_env(monkeypatch):
    """Remove todas as env vars que config.py lê ou escreve."""
    for var in (
        "READERFREE_CONFIG",
        "READERFREE_LIBRARY_DIR",
        "READERFREE_MODELS_DIR",
        "HF_HOME",
        "TRANSFORMERS_CACHE",
        "TORCH_HOME",
        "TTS_HOME",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_apply_model_cache_env_seta_vars_apontando_para_models_dir(tmp_path, clean_env):
    models = tmp_path / "models"
    paths = cfg.Paths(library_dir=tmp_path / "library", models_dir=models, config_file=None)

    cfg.apply_model_cache_env(paths)

    assert os.environ["HF_HOME"] == str(models)
    assert os.environ["TRANSFORMERS_CACHE"] == str(models / "huggingface")
    assert os.environ["TORCH_HOME"] == str(models / "torch")
    assert os.environ["TTS_HOME"] == str(models / "tts")
    assert os.environ["XDG_CACHE_HOME"] == str(models)


def test_apply_model_cache_env_cria_models_dir(tmp_path, clean_env):
    models = tmp_path / "nao_existe_ainda" / "models"
    assert not models.exists()

    paths = cfg.Paths(library_dir=tmp_path / "lib", models_dir=models, config_file=None)
    cfg.apply_model_cache_env(paths)

    assert models.is_dir()


def test_apply_model_cache_env_respeita_vars_pre_existentes(tmp_path, clean_env):
    """setdefault não sobrescreve — usuário pode ter HF_HOME próprio."""
    clean_env.setenv("HF_HOME", "/custom/hf")
    models = tmp_path / "models"
    paths = cfg.Paths(library_dir=tmp_path / "lib", models_dir=models, config_file=None)

    cfg.apply_model_cache_env(paths)

    assert os.environ["HF_HOME"] == "/custom/hf"
    # As outras, que não existiam, foram setadas normalmente
    assert os.environ["TORCH_HOME"] == str(models / "torch")


def test_resolve_paths_usa_env_vars(tmp_path, clean_env):
    lib = tmp_path / "custom_library"
    mod = tmp_path / "custom_models"
    clean_env.setenv("READERFREE_LIBRARY_DIR", str(lib))
    clean_env.setenv("READERFREE_MODELS_DIR", str(mod))

    paths = cfg.resolve_paths()

    assert paths.library_dir == lib
    assert paths.models_dir == mod


def test_resolve_paths_usa_config_toml(tmp_path, clean_env):
    cfg_file = tmp_path / "config.toml"
    lib = tmp_path / "toml_library"
    mod = tmp_path / "toml_models"
    cfg_file.write_text(
        f'[paths]\nlibrary_dir = "{lib.as_posix()}"\nmodels_dir = "{mod.as_posix()}"\n',
        encoding="utf-8",
    )
    clean_env.setenv("READERFREE_CONFIG", str(cfg_file))

    paths = cfg.resolve_paths()

    assert paths.library_dir == Path(lib.as_posix())
    assert paths.models_dir == Path(mod.as_posix())
    assert paths.config_file == cfg_file


def test_resolve_paths_env_tem_prioridade_sobre_toml(tmp_path, clean_env):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'[paths]\nlibrary_dir = "{(tmp_path / "toml_lib").as_posix()}"\n',
        encoding="utf-8",
    )
    clean_env.setenv("READERFREE_CONFIG", str(cfg_file))
    env_lib = tmp_path / "env_lib"
    clean_env.setenv("READERFREE_LIBRARY_DIR", str(env_lib))

    paths = cfg.resolve_paths()

    assert paths.library_dir == env_lib  # env ganha do toml


def test_resolve_device_sem_torch_retorna_cpu(clean_env, monkeypatch):
    """Sem torch instalado, 'auto' vira 'cpu'. Valores explícitos passam direto."""
    # Simula torch ausente
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch simulado ausente")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert cfg.resolve_device("auto") == "cpu"
    assert cfg.resolve_device("cpu") == "cpu"
    assert cfg.resolve_device("cuda") == "cuda"  # trust the caller
