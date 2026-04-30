"""Testes do worker (`src/worker.py`).

Usa `mock=True` no `BookMeta` pra evitar torch/XTTS — o worker chama
`build_book` real mas sem GPU. Cada teste para o worker no fim
(`stop()`).
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from src import library as lib
from src import worker

FIXTURES = Path(__file__).parent / "fixtures"


def _enqueue_brascubas(library_dir: Path, book_id: str = "bc") -> Path:
    """Cria um BookMeta + copia o TXT do Brás Cubas pra dentro da pasta."""
    book_dir = library_dir / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    src = book_dir / "source.txt"
    shutil.copy(FIXTURES / "bras_cubas_excerpt.txt", src)

    meta = lib.BookMeta(
        id=book_id,
        title="Brás Cubas",
        author="Machado de Assis",
        created_at=lib.now_iso(),
        source_file="source.txt",
        mock=True,
    )
    lib.write_book(library_dir, meta)
    lib.queue_push(library_dir, book_id)
    return book_dir


def _wait_status(library_dir: Path, book_id: str, target: str, timeout: float = 10.0):
    """Polling até o status virar `target`. Falha após timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            meta = lib.read_book(library_dir, book_id)
            if meta.status == target:
                return meta
            if meta.status in ("failed", "cancelled") and target == "ready":
                pytest.fail(f"esperava ready mas virou {meta.status}: {meta.failure_reason}")
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    pytest.fail(f"timeout esperando status={target} para {book_id}")


@pytest.fixture
def fresh_library(tmp_path):
    """Library nova + worker iniciado. Para no teardown."""
    lib.init_library(tmp_path)
    worker.start(tmp_path)
    yield tmp_path
    worker.stop(timeout=5.0)


# ============================================================================
# Processamento básico
# ============================================================================

def test_worker_processa_brascubas_em_mock(fresh_library):
    book_id = "bc"
    book_dir = _enqueue_brascubas(fresh_library, book_id)
    meta = _wait_status(fresh_library, book_id, "ready")
    assert meta.status == "ready"
    assert len(meta.chapters) == 1
    assert meta.chapters[0]["mp3_path"] == "chapter_01.mp3"
    # Arquivos físicos existem
    assert (book_dir / "chapter_01.mp3").exists()
    assert (book_dir / "chapter_01.vtt").exists()
    assert (book_dir / "chapter_01.txt").exists()
    assert (book_dir / "book.json").exists()
    # Mock regression preservada
    expected = (FIXTURES / "bras_cubas_excerpt.expected.vtt").read_text(encoding="utf-8")
    actual = (book_dir / "chapter_01.vtt").read_text(encoding="utf-8")
    assert actual == expected, "VTT do worker divergiu da fixture do mock"


def test_worker_processa_dois_livros_em_sequencia(fresh_library):
    _enqueue_brascubas(fresh_library, "a")
    _enqueue_brascubas(fresh_library, "b")
    _wait_status(fresh_library, "a", "ready")
    _wait_status(fresh_library, "b", "ready")
    assert lib.queue_list(fresh_library) == []


# ============================================================================
# Falhas
# ============================================================================

def test_worker_marca_failed_se_source_some(fresh_library):
    book_id = "missing"
    meta = lib.BookMeta(
        id=book_id, title="X", author=None, created_at=lib.now_iso(),
        source_file="not_there.txt", mock=True,
    )
    lib.write_book(fresh_library, meta)
    lib.queue_push(fresh_library, book_id)
    final = _wait_status(fresh_library, book_id, "failed")
    assert "não encontrado" in (final.failure_reason or "")


def test_worker_marca_failed_se_source_file_none(fresh_library):
    book_id = "no-source"
    meta = lib.BookMeta(
        id=book_id, title="X", author=None, created_at=lib.now_iso(),
        source_file=None, mock=True,
    )
    lib.write_book(fresh_library, meta)
    lib.queue_push(fresh_library, book_id)
    final = _wait_status(fresh_library, book_id, "failed")
    assert "source_file" in (final.failure_reason or "")


# ============================================================================
# Cancelamento
# ============================================================================

def test_cancel_livro_na_fila_remove_e_marca_cancelled(fresh_library):
    # Pausa worker pra livro ficar parado na fila.
    worker.pause()
    _enqueue_brascubas(fresh_library, "x")
    assert "x" in lib.queue_list(fresh_library)

    assert worker.cancel("x") is True
    # Removido da fila imediatamente
    assert "x" not in lib.queue_list(fresh_library)
    meta = lib.read_book(fresh_library, "x")
    assert meta.status == "cancelled"

    worker.resume()


def test_cancel_inexistente_retorna_false(fresh_library):
    assert worker.cancel("nao-existe") is False


# ============================================================================
# Pause/resume
# ============================================================================

def test_pause_segura_proximo_livro(fresh_library):
    worker.pause()
    _enqueue_brascubas(fresh_library, "p1")
    # Espera 1s pra confirmar que NÃO virou ready (worker pausado).
    time.sleep(1.0)
    meta = lib.read_book(fresh_library, "p1")
    assert meta.status == "queued"
    assert "p1" in lib.queue_list(fresh_library)

    worker.resume()
    _wait_status(fresh_library, "p1", "ready")
