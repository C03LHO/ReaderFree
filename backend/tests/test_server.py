"""Testes do servidor FastAPI (`server.py`).

Usa `httpx.AsyncClient` com `ASGITransport` — não sobe uvicorn real,
chama o app diretamente em memória. Library_dir é redirecionado pra
tmp_path via env var `READERFREE_LIBRARY_DIR`.

Todos os uploads usam `.txt` em mock mode pra evitar GPU.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def server_app(tmp_path, monkeypatch):
    """Cria server isolado em tmp_path. Faz setup manual (init_library +
    worker.start) porque `httpx.ASGITransport` não dispara lifespan por
    padrão. Worker é parado no teardown.

    Garante estado limpo do worker no setup (se um teste anterior deixou
    thread vazada, força stop antes de continuar) — evita race entre
    workers de testes consecutivos no Windows.
    """
    monkeypatch.setenv("READERFREE_LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setenv("READERFREE_MODELS_DIR", str(tmp_path / "models"))

    import importlib
    import server as srv_module
    srv_module = importlib.reload(srv_module)

    from src import config as cfg
    from src import library as lib
    from src import worker

    # Estado defensivo: força parar qualquer worker remanescente.
    worker.stop(timeout=5.0)

    library_dir = cfg.resolve_paths().library_dir
    lib.init_library(library_dir)
    worker.start(library_dir)
    srv_module.app.state.library_dir = library_dir

    yield srv_module

    worker.stop(timeout=5.0)


@pytest.fixture
async def client(server_app):
    """AsyncClient apontando pro app FastAPI em memória."""
    transport = httpx.ASGITransport(app=server_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _wait_status(server_app, book_id: str, target: str, timeout: float = 10.0):
    """Polling síncrono no library do server module pra aguardar status."""
    import time
    from src import library as lib

    library_dir = server_app.app.state.library_dir
    start = time.time()
    while time.time() - start < timeout:
        try:
            meta = lib.read_book(library_dir, book_id)
            if meta.status == target:
                return meta
            if target == "ready" and meta.status in ("failed", "cancelled"):
                pytest.fail(f"esperava ready, virou {meta.status}: {meta.failure_reason}")
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    pytest.fail(f"timeout esperando {target} para {book_id}")


# ============================================================================
# Health + endpoints triviais
# ============================================================================

@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_books_vazio_retorna_lista(client):
    r = await client.get("/books")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_book_inexistente_404(client):
    r = await client.get("/books/nao-existe")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_queue_inicial_vazia(client):
    r = await client.get("/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["queue"] == []
    assert body["paused"] is False


# ============================================================================
# Upload + processamento (mock)
# ============================================================================

@pytest.mark.asyncio
async def test_upload_txt_mock_processa_ate_ready(client, server_app):
    txt = (FIXTURES / "bras_cubas_excerpt.txt").read_bytes()
    r = await client.post(
        "/books?mock=true&title=Br%C3%A1s%20Cubas&author=Machado",
        files={"file": ("bras_cubas.txt", txt, "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    book_id = body["book_id"]
    assert body["duplicate"] is False
    assert book_id == "bras-cubas"

    # Espera worker terminar.
    _wait_status(server_app, book_id, "ready")

    # GET /books mostra o livro.
    r2 = await client.get("/books")
    assert any(b["id"] == book_id for b in r2.json())

    # GET /books/{id} traz o full meta.
    r3 = await client.get(f"/books/{book_id}")
    assert r3.status_code == 200
    full = r3.json()
    assert full["status"] == "ready"
    assert len(full["chapters"]) == 1
    assert full["mock"] is True
    assert full["author"] == "Machado"

    # Capa foi gerada (fallback procedural pra TXT).
    assert full["cover_path"] == "cover.jpg"
    r_cover = await client.get(f"/books/{book_id}/cover")
    assert r_cover.status_code == 200
    assert r_cover.headers["content-type"].startswith("image/")

    # GET assets do capítulo 1.
    r4 = await client.get(f"/books/{book_id}/chapters/1/audio")
    assert r4.status_code == 200
    assert r4.headers["content-type"].startswith("audio/mpeg")

    r5 = await client.get(f"/books/{book_id}/chapters/1/vtt")
    assert r5.status_code == 200
    assert r5.headers["content-type"].startswith("text/vtt")
    expected = (FIXTURES / "bras_cubas_excerpt.expected.vtt").read_bytes()
    assert r5.content == expected, "VTT do servidor divergiu da fixture do mock"


@pytest.mark.asyncio
async def test_upload_pdf_extrai_metadata_e_gera_capa(client, server_app, tmp_path):
    """PDF com metadata title/author no header → server usa esses valores
    e gera capa fallback (PDF tem só texto, sem imagem grande)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_title("Livro Detectado")
    pdf.set_author("Autor Detectado")
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    # Conteúdo significativo pra passar do limiar de "PDF escaneado".
    for _ in range(20):
        pdf.cell(0, 6, text="Era uma vez um livro com texto suficiente para ser extraído. " * 2, new_x="LMARGIN", new_y="NEXT")
    pdf_bytes_path = tmp_path / "x.pdf"
    pdf.output(str(pdf_bytes_path))
    pdf_bytes = pdf_bytes_path.read_bytes()

    # Upload sem passar title/author — deve detectar do PDF.
    r = await client.post(
        "/books?mock=true",
        files={"file": ("anonymous.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200
    book_id = r.json()["book_id"]
    assert book_id == "livro-detectado"

    _wait_status(server_app, book_id, "ready")
    full = (await client.get(f"/books/{book_id}")).json()
    assert full["title"] == "Livro Detectado"
    assert full["author"] == "Autor Detectado"
    assert full["cover_path"] == "cover.jpg"


@pytest.mark.asyncio
async def test_upload_extensao_invalida_400(client):
    r = await client.post(
        "/books",
        files={"file": ("oi.docx", b"qualquer", "application/octet-stream")},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_idempotente_por_hash(client, server_app):
    """Mesmo arquivo upado 2x retorna o mesmo book_id e duplicate=True."""
    txt = (FIXTURES / "bras_cubas_excerpt.txt").read_bytes()
    r1 = await client.post(
        "/books?mock=true",
        files={"file": ("a.txt", txt, "text/plain")},
    )
    book_id = r1.json()["book_id"]
    _wait_status(server_app, book_id, "ready")

    r2 = await client.post(
        "/books?mock=true&title=Outro%20T%C3%ADtulo",
        files={"file": ("b.txt", txt, "text/plain")},  # mesmo conteúdo, nome diferente
    )
    body = r2.json()
    assert body["book_id"] == book_id
    assert body["duplicate"] is True


# ============================================================================
# Delete + queue management
# ============================================================================

@pytest.mark.asyncio
async def test_delete_book(client, server_app):
    txt = (FIXTURES / "bras_cubas_excerpt.txt").read_bytes()
    r = await client.post("/books?mock=true", files={"file": ("a.txt", txt, "text/plain")})
    book_id = r.json()["book_id"]
    _wait_status(server_app, book_id, "ready")

    r2 = await client.delete(f"/books/{book_id}")
    assert r2.status_code == 200
    r3 = await client.get(f"/books/{book_id}")
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_delete_inexistente_404(client):
    r = await client.delete("/books/fake")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_queue_pause_resume(client, server_app):
    """Pausa, faz upload, confirma que ficou queued, retoma, espera ready."""
    pr = await client.post("/queue/pause")
    assert pr.json()["paused"] is True

    txt = (FIXTURES / "bras_cubas_excerpt.txt").read_bytes()
    r = await client.post("/books?mock=true", files={"file": ("p.txt", txt, "text/plain")})
    book_id = r.json()["book_id"]

    # Após upload, livro está queued.
    await asyncio.sleep(0.5)
    qb = await client.get(f"/books/{book_id}")
    assert qb.json()["status"] == "queued"

    rr = await client.post("/queue/resume")
    assert rr.json()["paused"] is False

    _wait_status(server_app, book_id, "ready")


@pytest.mark.asyncio
async def test_promote_inexistente_404(client):
    r = await client.post("/books/none/promote")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_chapter_audio_404_para_capitulo_inexistente(client, server_app):
    txt = (FIXTURES / "bras_cubas_excerpt.txt").read_bytes()
    r = await client.post("/books?mock=true", files={"file": ("a.txt", txt, "text/plain")})
    book_id = r.json()["book_id"]
    _wait_status(server_app, book_id, "ready")

    r2 = await client.get(f"/books/{book_id}/chapters/99/audio")
    assert r2.status_code == 404
    assert "fora do range" in r2.json()["detail"]
