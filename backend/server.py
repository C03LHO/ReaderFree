"""ReaderFree HTTP server (Fase 6.1).

FastAPI servindo a biblioteca local + endpoints CRUD para upload, listing,
delete, streaming de assets. Worker em thread separada consome a fila.

Por design, escuta apenas em `127.0.0.1:8765` por default — sem auth e
sem expor pra rede. Quando o usuário ativar "expor pra Tailscale" nas
Configurações (Fase 6.3+), passa a `0.0.0.0` com token Bearer.

Rodar manualmente:

    cd backend
    uvicorn server:app --host 127.0.0.1 --port 8765 --reload

Ou via launcher do desktop (Fase 6.4):

    python desktop/main.py
"""
from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src import config as cfg
from src import cover as cover_mod
from src import library as lib
from src import metadata as metadata_mod
from src import worker

# Windows console em cp1252 quebra com →/ç. Garante UTF-8 cedo.
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

logger = logging.getLogger(__name__)


# ---- Lifespan: inicia/para worker ---------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    paths = cfg.resolve_paths()
    library_dir = paths.library_dir
    lib.init_library(library_dir)
    worker.start(library_dir)
    app.state.library_dir = library_dir
    logger.info("ReaderFree server pronto. library=%s", library_dir)
    try:
        yield
    finally:
        worker.stop(timeout=5.0)


# ---- App ----------------------------------------------------------------

app = FastAPI(
    title="ReaderFree",
    description="Servidor local da biblioteca de audiobooks. Fonte da verdade.",
    version="0.6.1",
    lifespan=lifespan,
)

# CORS: o frontend Next em pnpm dev (porta 3000) precisa falar com 8765.
# Em produção desktop (PyWebview) é mesma origem.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Helpers ------------------------------------------------------------

def _library_dir(request: Request) -> Path:
    return request.app.state.library_dir


def _book_or_404(library_dir: Path, book_id: str) -> lib.BookMeta:
    try:
        return lib.read_book(library_dir, book_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Livro '{book_id}' não encontrado.")


def _chapter_or_404(meta: lib.BookMeta, n: int) -> dict:
    """`n` é 1-based (espelha o naming dos arquivos `chapter_NN`)."""
    if n < 1 or n > len(meta.chapters):
        raise HTTPException(
            status_code=404,
            detail=f"Capítulo {n} fora do range (livro tem {len(meta.chapters)}).",
        )
    return meta.chapters[n - 1]


def _book_dir(library_dir: Path, book_id: str) -> Path:
    return library_dir / book_id


# ---- Schemas (response) -------------------------------------------------

class BookSummary(BaseModel):
    id: str
    title: str
    author: Optional[str]
    status: str
    duration_seconds: float
    n_chapters: int
    created_at: str
    mock: bool
    cover_path: Optional[str]
    progress_phase: Optional[str]
    progress_current: int
    progress_total: int
    failure_reason: Optional[str]

    @classmethod
    def from_meta(cls, meta: lib.BookMeta) -> "BookSummary":
        return cls(
            id=meta.id,
            title=meta.title,
            author=meta.author,
            status=meta.status,
            duration_seconds=meta.duration_seconds,
            n_chapters=len(meta.chapters),
            created_at=meta.created_at,
            mock=meta.mock,
            cover_path=meta.cover_path,
            progress_phase=meta.progress_phase,
            progress_current=meta.progress_current,
            progress_total=meta.progress_total,
            failure_reason=meta.failure_reason,
        )


class BookFull(BaseModel):
    id: str
    title: str
    author: Optional[str]
    status: str
    duration_seconds: float
    chapters: list[dict]
    created_at: str
    mock: bool
    cover_path: Optional[str]
    progress_phase: Optional[str]
    progress_current: int
    progress_total: int
    failure_reason: Optional[str]
    schema_version: int

    @classmethod
    def from_meta(cls, meta: lib.BookMeta) -> "BookFull":
        return cls(**{f.name: getattr(meta, f.name) for f in lib.BookMeta.__dataclass_fields__.values()
                       if f.name not in ("source_file", "source_hash")})


class QueueStatus(BaseModel):
    queue: list[str]
    current: Optional[str]
    paused: bool


class UploadResponse(BaseModel):
    book_id: str
    duplicate: bool = Field(default=False, description="True se o hash bateu com livro existente.")


# ---- Endpoints: livros --------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/books", response_model=list[BookSummary])
async def list_books_endpoint(request: Request):
    library_dir = _library_dir(request)
    return [BookSummary.from_meta(m) for m in lib.list_books(library_dir)]


@app.get("/books/{book_id}", response_model=BookFull)
async def get_book(request: Request, book_id: str):
    meta = _book_or_404(_library_dir(request), book_id)
    return BookFull.from_meta(meta)


@app.delete("/books/{book_id}")
async def delete_book(request: Request, book_id: str):
    library_dir = _library_dir(request)
    # Cancela se em fila ou processamento.
    worker.cancel(book_id)
    if not lib.delete_book(library_dir, book_id):
        raise HTTPException(status_code=404, detail=f"Livro '{book_id}' não existe.")
    return {"deleted": book_id}


@app.post("/books", response_model=UploadResponse)
async def upload_book(
    request: Request,
    file: UploadFile = File(...),
    title: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    mock: bool = Query(False, description="Pula TTS/align reais — silêncio + VTT sintético."),
):
    library_dir = _library_dir(request)

    # Salva temporariamente em library_dir/_uploads/ pra hash + decisão.
    uploads = library_dir / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "input").suffix.lower()
    if suffix not in (".txt", ".pdf", ".epub"):
        raise HTTPException(
            status_code=400,
            detail=f"Extensão '{suffix}' não suportada. Use .txt, .pdf ou .epub.",
        )
    tmp = uploads / f"upload-{abs(hash(file.filename or '')):x}{suffix}"
    with tmp.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    source_hash = lib.hash_file(tmp)
    existing = lib.find_by_hash(library_dir, source_hash)
    if existing is not None:
        tmp.unlink(missing_ok=True)
        return UploadResponse(book_id=existing, duplicate=True)

    # Novo livro: extrai metadados nativos (title/author) com fallback no
    # nome do arquivo. Quem importou pode override via query params.
    info = metadata_mod.extract_info(tmp)
    book_title = title or info.title
    book_author = author or info.author

    book_id = lib.make_book_id(book_title)
    # Garante unicidade caso o slug colida (livros de mesmo título).
    library_dir_books = {b.id for b in lib.list_books(library_dir)}
    base = book_id
    counter = 1
    while book_id in library_dir_books:
        counter += 1
        book_id = f"{base}-{counter}"

    book_dir = library_dir / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    final_source = book_dir / f"source{suffix}"
    tmp.replace(final_source)

    # Capa: tenta extrair nativa do PDF/EPUB; se falhar, fallback procedural
    # com cor derivada do hash do título. Nunca falha — sempre escreve um
    # cover.jpg.
    cover_path: Optional[str] = None
    try:
        cover_path = cover_mod.write_cover(
            source_path=final_source,
            out_path=book_dir / "cover.jpg",
            title=book_title,
            author=book_author,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("upload: falha ao gerar capa pra %s: %s", book_id, exc)

    meta = lib.BookMeta(
        id=book_id,
        title=book_title,
        author=book_author,
        created_at=lib.now_iso(),
        source_file=final_source.name,
        source_hash=source_hash,
        cover_path=cover_path,
        mock=mock,
        status="queued",
    )
    lib.write_book(library_dir, meta)
    lib.queue_push(library_dir, book_id)
    return UploadResponse(book_id=book_id, duplicate=False)


# ---- Endpoints: assets de capítulo --------------------------------------

@app.get("/books/{book_id}/chapters/{n}/audio")
async def get_chapter_audio(request: Request, book_id: str, n: int):
    library_dir = _library_dir(request)
    meta = _book_or_404(library_dir, book_id)
    chapter = _chapter_or_404(meta, n)
    path = _book_dir(library_dir, book_id) / chapter["mp3_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="MP3 não gerado.")
    return FileResponse(path, media_type="audio/mpeg", filename=chapter["mp3_path"])


@app.get("/books/{book_id}/chapters/{n}/vtt")
async def get_chapter_vtt(request: Request, book_id: str, n: int):
    library_dir = _library_dir(request)
    meta = _book_or_404(library_dir, book_id)
    chapter = _chapter_or_404(meta, n)
    path = _book_dir(library_dir, book_id) / chapter["vtt_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="VTT não gerado.")
    return FileResponse(path, media_type="text/vtt", filename=chapter["vtt_path"])


@app.get("/books/{book_id}/chapters/{n}/text")
async def get_chapter_text(request: Request, book_id: str, n: int):
    library_dir = _library_dir(request)
    meta = _book_or_404(library_dir, book_id)
    chapter = _chapter_or_404(meta, n)
    path = _book_dir(library_dir, book_id) / chapter["text_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Texto não gerado.")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=chapter["text_path"])


@app.get("/books/{book_id}/cover")
async def get_book_cover(request: Request, book_id: str):
    library_dir = _library_dir(request)
    meta = _book_or_404(library_dir, book_id)
    if not meta.cover_path:
        raise HTTPException(status_code=404, detail="Sem capa (Fase 6.2 ainda não implementada).")
    path = _book_dir(library_dir, book_id) / meta.cover_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Arquivo de capa não encontrado: {meta.cover_path}")
    return FileResponse(path)


@app.get("/books/{book_id}/source")
async def get_book_source(request: Request, book_id: str):
    library_dir = _library_dir(request)
    meta = _book_or_404(library_dir, book_id)
    if not meta.source_file:
        raise HTTPException(status_code=404, detail="Sem arquivo de origem.")
    path = _book_dir(library_dir, book_id) / meta.source_file
    if not path.exists():
        raise HTTPException(status_code=404, detail="Source perdido em disco.")
    return FileResponse(path, filename=meta.source_file)


# ---- Endpoints: fila ----------------------------------------------------

@app.get("/queue", response_model=QueueStatus)
async def get_queue(request: Request):
    library_dir = _library_dir(request)
    return QueueStatus(
        queue=lib.queue_list(library_dir),
        current=worker.current_book_id(),
        paused=worker.is_paused(),
    )


@app.post("/queue/pause")
async def pause_queue():
    worker.pause()
    return {"paused": True}


@app.post("/queue/resume")
async def resume_queue():
    worker.resume()
    return {"paused": False}


@app.post("/books/{book_id}/promote")
async def promote_book(request: Request, book_id: str):
    library_dir = _library_dir(request)
    if not lib.queue_promote(library_dir, book_id):
        raise HTTPException(status_code=404, detail=f"'{book_id}' não está na fila.")
    return {"promoted": book_id, "queue": lib.queue_list(library_dir)}


# ---- Erros ---------------------------------------------------------------

@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---- Entry point uvicorn programático -----------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
