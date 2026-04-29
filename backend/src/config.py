"""Configuração do pipeline.

Resolução de paths em ordem de prioridade:
    1. Argumentos de CLI (--library-dir, --models-dir, --output)
    2. Variáveis de ambiente (READERFREE_LIBRARY_DIR, READERFREE_MODELS_DIR)
    3. `config.toml` (seção [paths]) em $READERFREE_CONFIG ou no diretório de
       dados do usuário do SO.
    4. Defaults por plataforma:
        - Windows: %LOCALAPPDATA%\\ReaderFree\\{library,models}
        - macOS:   ~/Library/Application Support/ReaderFree/{library,models}
        - Linux:   $XDG_DATA_HOME/ReaderFree/{library,models}

Nenhum path é hardcoded. O CWD nunca é assumido — quando empacotado (Fase 7.5),
o CWD é a pasta de instalação e isso tem que ser indiferente para o código.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "ReaderFree"

# ---- Constantes de pipeline (não são paths, então podem ser hardcoded).
XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
WHISPER_MODEL = "large-v3"
DEFAULT_LANGUAGE = "pt"
DEFAULT_CHUNK_CHARS = 250
MP3_BITRATE = "96k"
TTS_SAMPLE_RATE = 24000  # XTTS-v2 sintetiza a 24kHz


def _user_data_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / APP_NAME


def _read_config_toml(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _config_file_path() -> Path | None:
    env = os.environ.get("READERFREE_CONFIG")
    if env:
        return Path(env)
    candidate = _user_data_root() / "config.toml"
    return candidate if candidate.exists() else None


@dataclass(frozen=True)
class Paths:
    library_dir: Path
    models_dir: Path
    config_file: Path | None


def resolve_paths() -> Paths:
    config_file = _config_file_path()
    overrides = _read_config_toml(config_file).get("paths", {})
    root = _user_data_root()

    library = Path(
        os.environ.get("READERFREE_LIBRARY_DIR")
        or overrides.get("library_dir")
        or (root / "library")
    )
    models = Path(
        os.environ.get("READERFREE_MODELS_DIR")
        or overrides.get("models_dir")
        or (root / "models")
    )
    return Paths(library_dir=library, models_dir=models, config_file=config_file)


def apply_model_cache_env(paths: Paths) -> None:
    """Redireciona caches de HuggingFace / Coqui-TTS / Torch para paths.models_dir.

    Deve ser chamado *antes* de qualquer import de torch/TTS/whisperx para ter
    efeito. Os imports desses módulos são lazy — então chamar no início de cada
    função que invoca síntese/alinhamento já basta.
    """
    paths.models_dir.mkdir(parents=True, exist_ok=True)
    m = str(paths.models_dir)
    os.environ.setdefault("HF_HOME", m)
    os.environ.setdefault("TRANSFORMERS_CACHE", str(Path(m) / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(Path(m) / "torch"))
    os.environ.setdefault("TTS_HOME", str(Path(m) / "tts"))
    os.environ.setdefault("XDG_CACHE_HOME", m)


def resolve_device(device: str) -> str:
    """Resolve 'auto' → 'cuda' se disponível, senão 'cpu'. Lazy import de torch."""
    if device != "auto":
        return device
    try:
        import torch  # noqa: PLC0415 — lazy import é o ponto

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


# ---- Library v2 (Fase 6) ------------------------------------------------

LIBRARY_INDEX_FILE = "_index.json"
"""Nome do arquivo de índice global em `library_dir/`. Reflete metadados
agregados de todos os livros + estado da fila. Reconstrutível varrendo a
pasta se corromper (cada `meta.json` por livro é a fonte da verdade)."""

BOOK_META_FILE = "meta.json"
"""Nome do arquivo de metadados por livro em `library_dir/<book_id>/`."""

SCHEMA_VERSION = 2
"""Versão do schema do `meta.json`. v1 era a Fase 1 (book.json plano);
v2 inclui cover_path, source_file, source_hash, status, progress."""


def book_dir(library_dir: Path, book_id: str) -> Path:
    """Diretório de um livro específico em library v2."""
    return library_dir / book_id


def book_meta_path(library_dir: Path, book_id: str) -> Path:
    return book_dir(library_dir, book_id) / BOOK_META_FILE


def library_index_path(library_dir: Path) -> Path:
    return library_dir / LIBRARY_INDEX_FILE


@dataclass(frozen=True)
class PipelineConfig:
    language: str = DEFAULT_LANGUAGE
    device: str = "auto"
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    mp3_bitrate: str = MP3_BITRATE
    xtts_model: str = XTTS_MODEL
    whisper_model: str = WHISPER_MODEL
    sample_rate: int = TTS_SAMPLE_RATE
    mock: bool = False
