"""Library v2 — gerenciamento de livros em disco (Fase 6.1+).

Estrutura:

    %LOCALAPPDATA%\\ReaderFree\\library\\
    ├── _index.json                  # índice global (lista de livros + fila)
    ├── <book_id_a>/
    │   ├── meta.json                # metadados do livro (schema v2)
    │   ├── source.pdf               # arquivo de entrada original
    │   ├── cover.jpg                # capa (Fase 6.2)
    │   ├── chapter_01.mp3
    │   ├── chapter_01.vtt
    │   ├── chapter_01.txt
    │   └── ...
    └── <book_id_b>/...

`meta.json` por livro é a **fonte da verdade**. `_index.json` é cache
agregado reconstrutível — varrer a pasta e regravar.

Idempotência: re-upload do mesmo arquivo (mesmo `source_hash` sha256)
retorna o `book_id` existente em vez de duplicar.

Concurrency: `_index.json` é escrito em `_index.json.tmp` + rename
atômico para evitar leitor lendo metade. Worker e API rodam em threads
separadas — usamos `threading.RLock` em volta de operações de escrita.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config as cfg

# ---- Schema --------------------------------------------------------------

# Status possíveis de um livro:
#   queued      — na fila aguardando processamento
#   processing  — sendo processado pelo worker
#   ready       — pronto para tocar
#   failed      — processamento abortou (ver `failure_reason`)
#   cancelled   — usuário cancelou
BookStatus = str  # uma das constantes acima


@dataclass
class BookMeta:
    """Espelho persistido em `<book_id>/meta.json` (schema_version=2)."""
    id: str
    title: str
    author: Optional[str]
    created_at: str  # ISO 8601 UTC
    schema_version: int = cfg.SCHEMA_VERSION
    # Fluxo
    status: BookStatus = "queued"
    progress_phase: Optional[str] = None
    progress_current: int = 0
    progress_total: int = 0
    failure_reason: Optional[str] = None
    # Conteúdo
    duration_seconds: float = 0.0
    chapters: list[dict] = field(default_factory=list)
    mock: bool = False
    # Origem
    source_file: Optional[str] = None  # nome do arquivo dentro da pasta
    source_hash: Optional[str] = None  # sha256 hex do arquivo de entrada
    cover_path: Optional[str] = None   # nome do arquivo de capa, ex "cover.jpg"

    def to_json(self) -> dict:
        return asdict(self)


# ---- Operações de I/O ---------------------------------------------------

_lock = threading.RLock()


def init_library(library_dir: Path) -> None:
    """Garante que a pasta da biblioteca + index existem."""
    library_dir.mkdir(parents=True, exist_ok=True)
    idx = cfg.library_index_path(library_dir)
    if not idx.exists():
        _atomic_write_json(idx, {"books": [], "books_by_hash": {}, "queue": []})


def list_books(library_dir: Path) -> list[BookMeta]:
    """Lê o índice e retorna `BookMeta` reconstruídos a partir dos
    `meta.json` por livro. Se algum `meta.json` estiver inacessível,
    pula com warning.
    """
    init_library(library_dir)
    with _lock:
        idx = _read_json(cfg.library_index_path(library_dir))
        books: list[BookMeta] = []
        for book_id in idx.get("books", []):
            try:
                books.append(read_book(library_dir, book_id))
            except FileNotFoundError:
                # Pasta apagada à mão; deixamos o usuário re-indexar via reindex().
                continue
        return books


def read_book(library_dir: Path, book_id: str) -> BookMeta:
    """Lê `meta.json` de um livro específico."""
    p = cfg.book_meta_path(library_dir, book_id)
    if not p.exists():
        raise FileNotFoundError(f"meta.json não encontrado para '{book_id}'")
    data = _read_json(p)
    return _book_meta_from_dict(data)


def write_book(library_dir: Path, meta: BookMeta) -> None:
    """Escreve o `meta.json` do livro e atualiza o `_index.json`."""
    with _lock:
        init_library(library_dir)
        cfg.book_dir(library_dir, meta.id).mkdir(parents=True, exist_ok=True)
        _atomic_write_json(cfg.book_meta_path(library_dir, meta.id), meta.to_json())
        _ensure_in_index(library_dir, meta)


def update_book(library_dir: Path, book_id: str, **updates) -> BookMeta:
    """Lê, aplica updates parciais e escreve. Retorna o `BookMeta` final."""
    with _lock:
        meta = read_book(library_dir, book_id)
        for k, v in updates.items():
            setattr(meta, k, v)
        write_book(library_dir, meta)
        return meta


def delete_book(library_dir: Path, book_id: str) -> bool:
    """Remove pasta do livro + entrada do índice. Retorna True se existia."""
    with _lock:
        bd = cfg.book_dir(library_dir, book_id)
        if not bd.exists():
            return False
        # Remove arquivos da pasta + a pasta.
        for child in bd.iterdir():
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                # No nosso schema, livros não têm sub-pastas; mas robustece.
                _rmtree(child)
        bd.rmdir()
        _remove_from_index(library_dir, book_id)
        return True


def find_by_hash(library_dir: Path, source_hash: str) -> Optional[str]:
    """Retorna o `book_id` cujo `source_hash` bate, ou None."""
    init_library(library_dir)
    idx = _read_json(cfg.library_index_path(library_dir))
    return idx.get("books_by_hash", {}).get(source_hash)


def hash_file(path: Path) -> str:
    """sha256 hex do arquivo. Lê em chunks pra suportar PDFs grandes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_book_id(title: str) -> str:
    """Gera um `book_id` ASCII-safe a partir do título."""
    slug = _slugify(title)
    if not slug:
        slug = uuid.uuid4().hex[:8]
    return slug


# ---- Fila ---------------------------------------------------------------

def queue_push(library_dir: Path, book_id: str) -> None:
    """Adiciona ao fim da fila de processamento."""
    with _lock:
        idx_path = cfg.library_index_path(library_dir)
        idx = _read_json(idx_path)
        if book_id not in idx.setdefault("queue", []):
            idx["queue"].append(book_id)
            _atomic_write_json(idx_path, idx)


def queue_remove(library_dir: Path, book_id: str) -> None:
    with _lock:
        idx_path = cfg.library_index_path(library_dir)
        idx = _read_json(idx_path)
        q = idx.setdefault("queue", [])
        if book_id in q:
            q.remove(book_id)
            _atomic_write_json(idx_path, idx)


def queue_pop(library_dir: Path) -> Optional[str]:
    """Tira o próximo da fila (FIFO). Retorna None se vazia."""
    with _lock:
        idx_path = cfg.library_index_path(library_dir)
        idx = _read_json(idx_path)
        q = idx.setdefault("queue", [])
        if not q:
            return None
        book_id = q.pop(0)
        _atomic_write_json(idx_path, idx)
        return book_id


def queue_promote(library_dir: Path, book_id: str) -> bool:
    """Move o `book_id` para o topo da fila. Retorna True se estava na fila."""
    with _lock:
        idx_path = cfg.library_index_path(library_dir)
        idx = _read_json(idx_path)
        q = idx.setdefault("queue", [])
        if book_id not in q:
            return False
        q.remove(book_id)
        q.insert(0, book_id)
        _atomic_write_json(idx_path, idx)
        return True


def queue_list(library_dir: Path) -> list[str]:
    """Snapshot da fila atual, na ordem."""
    init_library(library_dir)
    idx = _read_json(cfg.library_index_path(library_dir))
    return list(idx.get("queue", []))


# ---- Internals -----------------------------------------------------------

def _ensure_in_index(library_dir: Path, meta: BookMeta) -> None:
    """Adiciona/atualiza entrada no `_index.json` (sem mexer na fila)."""
    idx_path = cfg.library_index_path(library_dir)
    idx = _read_json(idx_path)
    books = idx.setdefault("books", [])
    if meta.id not in books:
        books.append(meta.id)
    by_hash = idx.setdefault("books_by_hash", {})
    if meta.source_hash:
        by_hash[meta.source_hash] = meta.id
    _atomic_write_json(idx_path, idx)


def _remove_from_index(library_dir: Path, book_id: str) -> None:
    idx_path = cfg.library_index_path(library_dir)
    idx = _read_json(idx_path)
    books = idx.setdefault("books", [])
    if book_id in books:
        books.remove(book_id)
    by_hash = idx.setdefault("books_by_hash", {})
    for h, bid in list(by_hash.items()):
        if bid == book_id:
            del by_hash[h]
    q = idx.setdefault("queue", [])
    if book_id in q:
        q.remove(book_id)
    _atomic_write_json(idx_path, idx)


def _book_meta_from_dict(data: dict) -> BookMeta:
    """Constrói BookMeta a partir do dict serializado (tolerante a campos extras)."""
    fields = {f.name for f in BookMeta.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in fields}
    return BookMeta(**filtered)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: dict) -> None:
    """Escreve `path.tmp` e renomeia para `path` (atômico em mesmo volume)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _rmtree(path: Path) -> None:
    """Remove dir recursivamente sem depender de shutil (raro entrar aqui)."""
    for child in path.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


_SLUG_RE = re.compile(r"[^\w\s-]")
_SLUG_DASH_RE = re.compile(r"[\s_-]+")


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    cleaned = _SLUG_RE.sub("", ascii_only)
    return _SLUG_DASH_RE.sub("-", cleaned).strip("-")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
