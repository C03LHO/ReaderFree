"""Testes da library v2 (`src/library.py`).

Cobre persistência de meta.json, índice global, fila, idempotência por
hash, exclusão. Usa `tmp_path` — não toca em filesystem real.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import library as lib


def _make_meta(library_dir: Path, book_id: str = "x", title: str = "Livro X",
               source_hash: str | None = None) -> lib.BookMeta:
    """Helper: cria + persiste um BookMeta mínimo no library_dir."""
    meta = lib.BookMeta(
        id=book_id,
        title=title,
        author=None,
        created_at=lib.now_iso(),
        source_hash=source_hash,
    )
    lib.write_book(library_dir, meta)
    return meta


# ============================================================================
# Inicialização e índice
# ============================================================================

def test_init_library_cria_index_vazio(tmp_path):
    lib.init_library(tmp_path)
    idx_path = tmp_path / "_index.json"
    assert idx_path.exists()
    import json
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    assert idx == {"books": [], "books_by_hash": {}, "queue": []}


def test_init_library_idempotente(tmp_path):
    """Chamar 2x não sobrescreve dados existentes."""
    lib.init_library(tmp_path)
    _make_meta(tmp_path, book_id="x", source_hash="abc")

    # Re-init não apaga.
    lib.init_library(tmp_path)
    assert lib.find_by_hash(tmp_path, "abc") == "x"


# ============================================================================
# write_book / read_book
# ============================================================================

def test_write_e_read_book_roundtrip(tmp_path):
    lib.init_library(tmp_path)
    original = _make_meta(tmp_path, book_id="livro-1", title="Memórias", source_hash="h1")
    loaded = lib.read_book(tmp_path, "livro-1")
    assert loaded.id == "livro-1"
    assert loaded.title == "Memórias"
    assert loaded.source_hash == "h1"
    assert loaded.schema_version == 2


def test_read_book_inexistente_levanta(tmp_path):
    lib.init_library(tmp_path)
    with pytest.raises(FileNotFoundError):
        lib.read_book(tmp_path, "nao-existe")


def test_write_book_cria_pasta_do_livro(tmp_path):
    _make_meta(tmp_path, book_id="cap-livro")
    assert (tmp_path / "cap-livro").is_dir()
    assert (tmp_path / "cap-livro" / "meta.json").is_file()


def test_update_book_aplica_partial(tmp_path):
    _make_meta(tmp_path, book_id="x", title="Antigo")
    lib.update_book(tmp_path, "x", title="Novo", status="ready")
    meta = lib.read_book(tmp_path, "x")
    assert meta.title == "Novo"
    assert meta.status == "ready"


# ============================================================================
# list_books
# ============================================================================

def test_list_books_vazio(tmp_path):
    assert lib.list_books(tmp_path) == []


def test_list_books_retorna_todos(tmp_path):
    _make_meta(tmp_path, book_id="a")
    _make_meta(tmp_path, book_id="b")
    _make_meta(tmp_path, book_id="c")
    ids = sorted(b.id for b in lib.list_books(tmp_path))
    assert ids == ["a", "b", "c"]


def test_list_books_pula_pasta_apagada_a_mao(tmp_path):
    """Se o usuário apagar uma pasta no Explorer, list_books pula com warning."""
    _make_meta(tmp_path, book_id="a")
    _make_meta(tmp_path, book_id="b")
    # Simula apagar a pasta b/ deixando b no índice.
    (tmp_path / "b" / "meta.json").unlink()
    (tmp_path / "b").rmdir()
    books = lib.list_books(tmp_path)
    assert [b.id for b in books] == ["a"]


# ============================================================================
# Hash + idempotência
# ============================================================================

def test_hash_file_consistente(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc" * 1000)
    h1 = lib.hash_file(f)
    h2 = lib.hash_file(f)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_hash_file_difere_por_conteudo(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"foo")
    b.write_bytes(b"bar")
    assert lib.hash_file(a) != lib.hash_file(b)


def test_find_by_hash_indexa_livro(tmp_path):
    _make_meta(tmp_path, book_id="hashed", source_hash="abc123")
    assert lib.find_by_hash(tmp_path, "abc123") == "hashed"


def test_find_by_hash_inexistente_retorna_none(tmp_path):
    lib.init_library(tmp_path)
    assert lib.find_by_hash(tmp_path, "ainda-nao") is None


# ============================================================================
# delete_book
# ============================================================================

def test_delete_book_remove_pasta_e_indice(tmp_path):
    _make_meta(tmp_path, book_id="x", source_hash="abc")
    assert lib.delete_book(tmp_path, "x") is True
    assert not (tmp_path / "x").exists()
    assert lib.find_by_hash(tmp_path, "abc") is None
    assert lib.list_books(tmp_path) == []


def test_delete_book_inexistente_retorna_false(tmp_path):
    lib.init_library(tmp_path)
    assert lib.delete_book(tmp_path, "nao-existe") is False


def test_delete_book_remove_da_fila_tambem(tmp_path):
    _make_meta(tmp_path, book_id="x")
    lib.queue_push(tmp_path, "x")
    lib.delete_book(tmp_path, "x")
    assert lib.queue_list(tmp_path) == []


# ============================================================================
# Fila
# ============================================================================

def test_queue_push_pop_fifo(tmp_path):
    lib.init_library(tmp_path)
    lib.queue_push(tmp_path, "a")
    lib.queue_push(tmp_path, "b")
    lib.queue_push(tmp_path, "c")
    assert lib.queue_pop(tmp_path) == "a"
    assert lib.queue_pop(tmp_path) == "b"
    assert lib.queue_pop(tmp_path) == "c"
    assert lib.queue_pop(tmp_path) is None


def test_queue_push_idempotente(tmp_path):
    lib.init_library(tmp_path)
    lib.queue_push(tmp_path, "a")
    lib.queue_push(tmp_path, "a")
    assert lib.queue_list(tmp_path) == ["a"]


def test_queue_promote_move_para_topo(tmp_path):
    lib.init_library(tmp_path)
    for x in ["a", "b", "c"]:
        lib.queue_push(tmp_path, x)
    assert lib.queue_promote(tmp_path, "c") is True
    assert lib.queue_list(tmp_path) == ["c", "a", "b"]


def test_queue_promote_inexistente_retorna_false(tmp_path):
    lib.init_library(tmp_path)
    lib.queue_push(tmp_path, "a")
    assert lib.queue_promote(tmp_path, "naotem") is False
    assert lib.queue_list(tmp_path) == ["a"]


def test_queue_remove(tmp_path):
    lib.init_library(tmp_path)
    lib.queue_push(tmp_path, "a")
    lib.queue_push(tmp_path, "b")
    lib.queue_remove(tmp_path, "a")
    assert lib.queue_list(tmp_path) == ["b"]


# ============================================================================
# make_book_id
# ============================================================================

def test_make_book_id_slugifica():
    assert lib.make_book_id("Memórias Póstumas de Brás Cubas") == "memorias-postumas-de-bras-cubas"
    assert lib.make_book_id("  oi  mundo!  ") == "oi-mundo"


def test_make_book_id_titulo_so_simbolos_gera_uuid():
    bid = lib.make_book_id("@#$%")
    assert len(bid) == 8  # uuid hex truncado


# ============================================================================
# Atomicidade: write não deixa _index.json corrompido
# ============================================================================

def test_atomic_write_nao_deixa_arquivo_meio_escrito(tmp_path):
    """Smoke check do atomic write — dificil de reproduzir crash mid-write,
    mas garantimos que não sobra _index.json.tmp pendurado."""
    _make_meta(tmp_path, book_id="x")
    files = sorted(p.name for p in tmp_path.iterdir())
    assert "_index.json" in files
    assert "_index.json.tmp" not in files
