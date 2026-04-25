"""Extração de texto a partir de arquivos .pdf.

Estratégia (decisão da Fase 2 — ver `docs/phase2-research.md` § 1):

1. **pypdf por padrão.** Empata com PyMuPDF em qualidade e tem licença
   permissiva (BSD); evita o problema da AGPL do PyMuPDF.
2. **Detecção de PDF escaneado:** se o texto extraído tem menos de
   `MIN_CHARS_PER_PAGE` chars por página em média, abortamos com mensagem
   instrutiva. O usuário roda `ocrmypdf` manualmente, ou passa `auto_ocr=True`.
3. **OCR opt-in:** com `auto_ocr=True` e `ocrmypdf` no PATH, rodamos
   `ocrmypdf --skip-text --language por` antes da extração e seguimos no
   PDF rasterizado/processado.
4. **Capítulos via outline.** Se o PDF tiver bookmarks, cada um vira um
   capítulo. Sem outline, fallback é regex de heading (CAPÍTULO X, "1. Foo");
   sem nada disso, capítulo único.
5. **Hifenização de fim de linha.** Trataremos `palavra-\\npalavra` →
   `palavrapalavra` no pós-processamento, preservando hífens "legítimos"
   (compostos: `bem-estar`).
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Configuração da heurística -------------------------------------------

MIN_CHARS_PER_PAGE = 100
"""Limiar abaixo do qual consideramos o PDF "escaneado" (sem camada de texto).

Páginas de livro típicas têm 1500–2500 chars. Front matter (capa, rosto)
puxa a média pra baixo, mas raramente abaixo de 100 num livro inteiro de
200+ páginas. Falso positivo teórico: álbum fotográfico só com legendas curtas.
"""


# --- Heading detection regexes --------------------------------------------

_CHAPTER_HEADING_PATTERNS = [
    # "CAPÍTULO 1", "Capítulo I", "CAPITULO IX" (com ou sem acento)
    re.compile(r"^\s*(CAP[IÍ]TULO|Cap[ií]tulo)\s+(\d+|[IVXLCDMivxlcdm]+)\b.*$", re.MULTILINE),
    # "1. Título", "12. Título começando com maiúscula"
    re.compile(r"^\s*(\d+)\.\s+[A-ZÁÉÍÓÚÀÃÕÂÊÎÔÛÇ][^\n]{0,80}$", re.MULTILINE),
]


# --- API pública ----------------------------------------------------------

def extract(path: Path, auto_ocr: bool = False) -> list[dict]:
    """Extrai capítulos de um PDF.

    Args:
        path: caminho do PDF.
        auto_ocr: se True e `ocrmypdf` estiver no PATH, roda OCR antes da
            extração (gera um PDF temporário ao lado do original). Default
            False — preferimos falhar cedo com instrução.

    Returns:
        Lista de capítulos no formato ``[{"title": str, "text": str}]``.
        Pelo menos 1 capítulo se a extração der certo.

    Raises:
        ValueError: PDF parece escaneado e `auto_ocr=False`, ou OCR pedido
            mas `ocrmypdf` não está no PATH.
    """
    from pypdf import PdfReader  # lazy import (consistência com tts/align)

    source = path
    if auto_ocr:
        source = _run_ocrmypdf(path)

    reader = PdfReader(str(source))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n".join(pages_text)

    # Detecção de PDF escaneado: depois da tentativa, se sobrou pouco texto.
    avg_chars = len(full_text) / max(len(pages_text), 1)
    if avg_chars < MIN_CHARS_PER_PAGE and not auto_ocr:
        raise ValueError(
            f"PDF parece escaneado (apenas {avg_chars:.0f} chars/página extraídos, "
            f"limiar = {MIN_CHARS_PER_PAGE}).\n"
            f"Soluções:\n"
            f"  1) Rode 'ocrmypdf --language por {path.name} {path.stem}_ocr.pdf' "
            f"antes e use {path.stem}_ocr.pdf.\n"
            f"  2) Ou passe --auto-ocr (requer ocrmypdf no PATH)."
        )
    if avg_chars < MIN_CHARS_PER_PAGE and auto_ocr:
        # OCR rodou mas ainda saiu pouco — provavelmente PDF de imagens vazias.
        raise ValueError(
            f"PDF continua sem texto extraível mesmo após OCR "
            f"({avg_chars:.0f} chars/página). Verifique se o original tem texto legível."
        )

    # Limpeza pré-segmentação: hifenização e espaços.
    full_text = _dehyphenate(full_text)
    full_text = _normalize_spaces(full_text)

    # Tenta capítulos via outline; senão regex; senão capítulo único.
    chapters = _split_by_outline(reader, pages_text)
    if chapters is None:
        chapters = _split_by_heading_regex(full_text)
    if chapters is None:
        chapters = [{"title": path.stem.replace("_", " ").strip() or "Sem título",
                     "text": full_text}]

    # Limpeza por capítulo + remoção de capítulos vazios.
    chapters = [
        {"title": c["title"], "text": _normalize_spaces(_dehyphenate(c["text"])).strip()}
        for c in chapters
        if c["text"].strip()
    ]
    if not chapters:
        raise ValueError(f"PDF '{path.name}' não rendeu nenhum capítulo com texto.")
    return chapters


# --- Internals ------------------------------------------------------------

def _run_ocrmypdf(path: Path) -> Path:
    """Roda `ocrmypdf --skip-text --language por` no PDF, retorna caminho do output.

    Erro se `ocrmypdf` não estiver no PATH.
    """
    if shutil.which("ocrmypdf") is None:
        raise ValueError(
            "--auto-ocr passado, mas 'ocrmypdf' não está no PATH. "
            "Instale com 'pip install ocrmypdf' ou veja https://ocrmypdf.readthedocs.io/."
        )
    out_path = path.with_name(f"{path.stem}_ocr.pdf")
    logger.info("Rodando ocrmypdf em %s -> %s (pode demorar)", path.name, out_path.name)
    cmd = ["ocrmypdf", "--skip-text", "--language", "por", str(path), str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError(
            f"ocrmypdf falhou (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return out_path


def _dehyphenate(text: str) -> str:
    """Junta palavras quebradas no fim de linha por hifenização.

    `recomen-\\ndação` → `recomendação`. Não toca em hífens "legítimos"
    (compostos como `bem-estar`) porque eles não estão colados em quebra de
    linha. Heurística simples mas eficaz para PDFs de livro.

    Casos como `multi-\\nuser` (palavra com hífen real quebrada na linha)
    ficam como `multiuser` — falso positivo aceitável; raríssimo em livros
    em pt-br.
    """
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def _normalize_spaces(text: str) -> str:
    """Colapsa whitespace preservando parágrafos (linhas em branco duplas)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Em PDFs, linhas individuais geralmente são quebras de layout, não de
    # parágrafo. Junta linhas individuais; preserva apenas \n\n+ como parágrafo.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _split_by_outline(reader, pages_text: list[str]) -> list[dict] | None:
    """Tenta dividir o livro pelos bookmarks do PDF.

    Retorna None se não houver outline ou se ele estiver vazio.
    """
    try:
        outline = reader.outline
    except Exception:
        return None
    if not outline:
        return None

    flat = _flatten_outline(reader, outline)
    if len(flat) < 2:
        # 1 bookmark só não vale a pena; vira capítulo único pela outra via.
        return None

    chapters: list[dict] = []
    for i, (title, page_idx) in enumerate(flat):
        end_page = flat[i + 1][1] if i + 1 < len(flat) else len(pages_text)
        text = "\n".join(pages_text[page_idx:end_page])
        chapters.append({"title": title, "text": text})
    return chapters


def _flatten_outline(reader, outline) -> list[tuple[str, int]]:
    """Achata um outline aninhado em [(titulo, page_index), ...].

    Bookmarks aninhados (subseções) são incluídos como capítulos próprios —
    para audiobook, isso geralmente é ruim, mas usuário pode usar
    --chapters-only para filtrar.
    """
    flat: list[tuple[str, int]] = []
    for item in outline:
        if isinstance(item, list):
            flat.extend(_flatten_outline(reader, item))
            continue
        try:
            title = str(item.title or "").strip() or "Sem título"
            page_idx = reader.get_destination_page_number(item)
        except Exception:
            continue
        flat.append((title, page_idx))
    flat.sort(key=lambda t: t[1])
    return flat


def _split_by_heading_regex(text: str) -> list[dict] | None:
    """Tenta detectar capítulos por padrões de heading.

    Retorna None se < 2 matches ou se eles estão muito juntos
    (provavelmente lixo: numeração de página, footnotes etc.).
    """
    matches: list[tuple[int, str]] = []
    for pattern in _CHAPTER_HEADING_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), m.group(0).strip()))
    if len(matches) < 2:
        return None

    matches.sort()
    # Filtra heads suspeitamente próximos (<500 chars entre si): provavelmente
    # numeração de página ou índice repetido.
    filtered: list[tuple[int, str]] = [matches[0]]
    for pos, title in matches[1:]:
        if pos - filtered[-1][0] >= 500:
            filtered.append((pos, title))
    if len(filtered) < 2:
        return None

    chapters: list[dict] = []
    for i, (start, title) in enumerate(filtered):
        end = filtered[i + 1][0] if i + 1 < len(filtered) else len(text)
        body = text[start:end].split("\n", 1)
        body_text = body[1] if len(body) > 1 else ""
        chapters.append({"title": title, "text": body_text})
    return chapters
