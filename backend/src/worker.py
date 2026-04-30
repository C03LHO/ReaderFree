"""Worker de processamento de livros (Fase 6.1+).

Thread em background que consome a fila de `_index.json` e executa
`build.build_book` num livro por vez (sequencial — uma GPU = uma
inferência XTTS).

Suporta:
- **Cancelamento de uma tarefa específica**: `cancel(book_id)` seta uma
  flag verificada pelo `build_book` entre chunks. Se for o livro em
  processamento agora, a inferência aborta limpa; se for um livro na
  fila, é removido sem ter sido processado.
- **Pause global**: `pause()`/`resume()` faz o worker parar de pegar
  novos itens da fila. Tarefa em andamento continua até o fim (ou até
  ser cancelada manualmente).
- **Promote**: na verdade implementado em `library.queue_promote` — o
  worker apenas lê o topo da fila a cada iteração.

O worker reporta progresso atualizando o `meta.json` do livro
(`status`, `progress_phase`, `progress_current`, `progress_total`,
`failure_reason`). O cliente HTTP faz polling de 1s no
`GET /books/{id}` ou `GET /books/{id}/progress`.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import library as lib
from .build import BuildCancelled, BuildProgress, build_book

logger = logging.getLogger(__name__)


# ---- Estado global do worker --------------------------------------------

@dataclass
class WorkerState:
    """Estado partilhado entre worker thread e API thread.

    Tudo aqui é mexido sob `_state_lock` ou via threading.Event.
    """
    library_dir: Path
    paused: threading.Event           # set = pausado, clear = ativo
    stop: threading.Event             # set = worker thread deve sair
    current_book_id: Optional[str] = None
    cancel_requests: set[str] = None  # book_ids a cancelar (corrente ou na fila)

    def __post_init__(self):
        if self.cancel_requests is None:
            self.cancel_requests = set()


_state: Optional[WorkerState] = None
_state_lock = threading.RLock()
_thread: Optional[threading.Thread] = None


# ---- API pública --------------------------------------------------------

def start(library_dir: Path) -> None:
    """Inicia o worker thread. Idempotente — chamar 2x não duplica."""
    global _state, _thread
    with _state_lock:
        if _thread and _thread.is_alive():
            return
        _state = WorkerState(
            library_dir=library_dir,
            paused=threading.Event(),
            stop=threading.Event(),
        )
        _thread = threading.Thread(target=_worker_loop, daemon=True, name="reader-free-worker")
        _thread.start()


def stop(timeout: float = 5.0) -> None:
    """Sinaliza ao worker para sair e espera. Cancela tarefa corrente."""
    global _state, _thread
    with _state_lock:
        if _state is None or _thread is None:
            return
        # Cancela qualquer livro em processamento.
        if _state.current_book_id:
            _state.cancel_requests.add(_state.current_book_id)
        _state.stop.set()
        _state.paused.clear()  # libera o sleep da pausa
        thread_to_join = _thread
    thread_to_join.join(timeout=timeout)
    with _state_lock:
        _thread = None
        _state = None


def pause() -> None:
    """Pausa o worker entre tarefas. Tarefa em andamento continua."""
    with _state_lock:
        if _state is not None:
            _state.paused.set()


def resume() -> None:
    """Tira da pausa."""
    with _state_lock:
        if _state is not None:
            _state.paused.clear()


def is_paused() -> bool:
    with _state_lock:
        return _state is not None and _state.paused.is_set()


def cancel(book_id: str) -> bool:
    """Marca um book_id pra cancelamento.

    - Se for o em processamento agora: aborta limpa entre chunks.
    - Se estiver na fila: remove sem processar.

    Retorna True se houve algo pra cancelar.
    """
    with _state_lock:
        if _state is None:
            return False
        is_current = _state.current_book_id == book_id
        in_queue = book_id in lib.queue_list(_state.library_dir)
        if not is_current and not in_queue:
            return False
        _state.cancel_requests.add(book_id)
        # Se ainda está na fila, remove direto (não vai chegar a processar).
        if in_queue and not is_current:
            lib.queue_remove(_state.library_dir, book_id)
            try:
                lib.update_book(
                    _state.library_dir, book_id,
                    status="cancelled",
                    failure_reason="Cancelado pelo usuário antes de iniciar",
                )
            except FileNotFoundError:
                pass
            _state.cancel_requests.discard(book_id)
        return True


def current_book_id() -> Optional[str]:
    with _state_lock:
        return _state.current_book_id if _state else None


# ---- Loop interno -------------------------------------------------------

def _worker_loop() -> None:
    """Loop principal do worker. Sai quando stop está set."""
    assert _state is not None
    state = _state
    logger.info("worker iniciado em %s", state.library_dir)

    while not state.stop.is_set():
        # Pause check: dorme em busy-wait suave até des-pausar ou stop.
        if state.paused.is_set():
            time.sleep(0.5)
            continue

        book_id = lib.queue_pop(state.library_dir)
        if book_id is None:
            time.sleep(0.5)  # fila vazia, espera 500ms e tenta de novo
            continue

        with _state_lock:
            state.current_book_id = book_id

        try:
            _process_book(state, book_id)
        except Exception:  # noqa: BLE001 — qualquer erro vira "failed" no meta
            logger.exception("worker: falha inesperada processando %s", book_id)
            try:
                lib.update_book(
                    state.library_dir, book_id,
                    status="failed",
                    failure_reason=traceback.format_exc(limit=3),
                )
            except FileNotFoundError:
                pass
        finally:
            with _state_lock:
                state.current_book_id = None
                state.cancel_requests.discard(book_id)

    logger.info("worker encerrado")


def _process_book(state: WorkerState, book_id: str) -> None:
    """Processa um livro individual."""
    try:
        meta = lib.read_book(state.library_dir, book_id)
    except FileNotFoundError:
        logger.warning("worker: meta de %s sumiu, pulando", book_id)
        return

    # Cancelado antes de começar?
    if book_id in state.cancel_requests:
        lib.update_book(
            state.library_dir, book_id,
            status="cancelled",
            failure_reason="Cancelado antes de iniciar",
        )
        return

    if meta.source_file is None:
        lib.update_book(
            state.library_dir, book_id,
            status="failed",
            failure_reason="meta.source_file é None — nada para processar",
        )
        return

    book_dir = state.library_dir / book_id
    source_path = book_dir / meta.source_file
    if not source_path.exists():
        lib.update_book(
            state.library_dir, book_id,
            status="failed",
            failure_reason=f"arquivo de origem não encontrado: {source_path.name}",
        )
        return

    # Marca como processing. Limpa progresso anterior.
    lib.update_book(
        state.library_dir, book_id,
        status="processing",
        progress_phase="extract",
        progress_current=0,
        progress_total=1,
        failure_reason=None,
    )

    def on_progress(ev: BuildProgress) -> None:
        try:
            lib.update_book(
                state.library_dir, book_id,
                progress_phase=ev.phase,
                progress_current=ev.current,
                progress_total=ev.total,
            )
        except FileNotFoundError:
            pass  # livro deletado mid-process

    def cancel_check() -> bool:
        return book_id in state.cancel_requests or state.stop.is_set()

    try:
        result = build_book(
            input_path=source_path,
            output_dir=book_dir,
            mock=meta.mock,
            title=meta.title,
            author=meta.author,
            on_progress=on_progress,
            cancel=cancel_check,
        )
    except BuildCancelled:
        lib.update_book(
            state.library_dir, book_id,
            status="cancelled",
            failure_reason="Cancelado durante processamento",
        )
        return
    except ValueError as exc:
        lib.update_book(
            state.library_dir, book_id,
            status="failed",
            failure_reason=str(exc),
        )
        return

    # Sucesso. Copia metadata derivada (chapters + duration) para o meta.json.
    lib.update_book(
        state.library_dir, book_id,
        status="ready",
        progress_phase=None,
        progress_current=0,
        progress_total=0,
        chapters=result.get("chapters", []),
        duration_seconds=result.get("duration_seconds", 0.0),
    )
