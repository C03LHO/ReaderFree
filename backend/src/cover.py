"""Extração / geração de capa de livro (Fase 6.2).

Cascata:
  1. PDF: tenta extrair a primeira imagem da primeira página (>= 60% da
     área). Se falhar, fallback procedural.
  2. EPUB: lê o OPF procurando item com `properties="cover-image"` (EPUB 3)
     ou `<meta name="cover">` (EPUB 2). Se não houver, fallback procedural.
  3. TXT (e qualquer outro): vai direto pro fallback procedural.

Capa final é sempre normalizada para JPG 600x900 (proporção típica de
livro). Salva em `<book_dir>/cover.jpg`.

Fallback procedural: PIL gera 600x900 com cor sólida derivada do hash
do título + título e (opcionalmente) autor centralizados em fonte
default. Estética minimalista, sem font extra-loading.
"""
from __future__ import annotations

import hashlib
import io
import logging
import warnings
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Tamanho final padrão (proporção 2:3 — livro de bolso típico).
COVER_W = 600
COVER_H = 900
COVER_MIN_AREA_RATIO = 0.6  # PDF: imagem precisa cobrir 60%+ da página


def write_cover(
    source_path: Path,
    out_path: Path,
    title: str,
    author: Optional[str] = None,
) -> str:
    """Gera/extrai a capa do livro e grava em `out_path` (JPG).

    Returns:
        O caminho relativo (`out_path.name`) — pronto pra guardar em
        `meta.cover_path`.
    """
    image_bytes = _try_extract(source_path)
    if image_bytes is None:
        image_bytes = _generate_fallback(title, author)
    _write_jpg(image_bytes, out_path)
    return out_path.name


# ---- Cascata de extração -----------------------------------------------

def _try_extract(source_path: Path) -> Optional[bytes]:
    """Tenta extrair capa nativa. Retorna PNG/JPEG bytes ou None."""
    ext = source_path.suffix.lower()
    if ext == ".pdf":
        return _from_pdf(source_path)
    if ext == ".epub":
        return _from_epub(source_path)
    return None


def _from_pdf(path: Path) -> Optional[bytes]:
    """Extrai a primeira imagem grande da primeira página de um PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        logger.info("cover: pypdf falhou em %s: %s", path.name, exc)
        return None
    if not reader.pages:
        return None
    page = reader.pages[0]
    try:
        # mediabox dá largura x altura em pontos PDF.
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)
    except Exception:
        return None
    page_area = max(1.0, page_w * page_h)

    images = getattr(page, "images", None)
    if not images:
        return None
    for img_obj in images:
        # `img_obj` tem .data (bytes), .name, .image (PIL.Image).
        try:
            pil_img = img_obj.image
        except Exception:
            continue
        if pil_img is None:
            continue
        # Compara área da imagem com a página (em pontos PDF — proxy decente).
        # Use width*height da imagem em pixels, normalizada por dpi=72 default.
        # Heurística simples: assume 1pt = 1px se não tiver info de dpi.
        img_w, img_h = pil_img.size
        area_ratio = (img_w * img_h) / page_area
        if area_ratio >= COVER_MIN_AREA_RATIO:
            buf = io.BytesIO()
            pil_img.convert("RGB").save(buf, format="JPEG", quality=85)
            return buf.getvalue()
    return None


def _from_epub(path: Path) -> Optional[bytes]:
    """Lê o item `cover-image` do EPUB."""
    try:
        from ebooklib import ITEM_COVER, ITEM_IMAGE, epub
    except ImportError:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(str(path))
    except Exception as exc:
        logger.info("cover: ebooklib falhou em %s: %s", path.name, exc)
        return None

    # EPUB 3: items com properties="cover-image" são marcados como ITEM_COVER.
    for item in book.get_items_of_type(ITEM_COVER):
        content = item.get_content()
        if content:
            return bytes(content)

    # EPUB 2: `<meta name="cover" content="cover-id">` aponta para um item de
    # imagem. ebooklib expõe via metadata.
    try:
        meta_list = book.get_metadata("OPF", "cover")
    except Exception:
        meta_list = []
    cover_id: Optional[str] = None
    for _, attrs in meta_list:
        if isinstance(attrs, dict) and attrs.get("content"):
            cover_id = attrs["content"]
            break
    if cover_id:
        item = book.get_item_with_id(cover_id)
        if item is not None and item.get_type() == ITEM_IMAGE:
            content = item.get_content()
            if content:
                return bytes(content)

    return None


# ---- Fallback procedural via PIL ---------------------------------------

def _generate_fallback(title: str, author: Optional[str]) -> bytes:
    """Cria capa minimalista 600x900 com cor de fundo derivada do título."""
    from PIL import Image, ImageDraw, ImageFont

    bg = _color_from_title(title)
    img = Image.new("RGB", (COVER_W, COVER_H), bg)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(48)
    author_font = _load_font(28)

    # Quebra título em linhas que cabem em ~80% da largura.
    title_lines = _wrap_text(draw, title, title_font, max_w=int(COVER_W * 0.8))
    line_h_title = title_font.size + 12

    # Posição vertical: centro da capa, com autor logo abaixo.
    block_h = line_h_title * len(title_lines)
    if author:
        block_h += 20 + author_font.size

    y = (COVER_H - block_h) // 2
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_w = bbox[2] - bbox[0]
        x = (COVER_W - line_w) // 2
        draw.text((x, y), line, fill=_text_color_for(bg), font=title_font)
        y += line_h_title

    if author:
        y += 20
        bbox = draw.textbbox((0, 0), author, font=author_font)
        line_w = bbox[2] - bbox[0]
        x = (COVER_W - line_w) // 2
        draw.text((x, y), author, fill=_text_color_for(bg), font=author_font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _color_from_title(title: str) -> tuple[int, int, int]:
    """Cor RGB pseudo-aleatória derivada do hash do título.

    Mantém saturação média e luminosidade moderada para o texto branco
    contrastar bem.
    """
    h = hashlib.sha256(title.encode("utf-8")).digest()
    # Pega 3 bytes do hash, mapeia pra range 60-180 (não muito escuro nem
    # muito claro — texto branco lê bem).
    r = 60 + (h[0] % 121)
    g = 60 + (h[1] % 121)
    b = 60 + (h[2] % 121)
    return (r, g, b)


def _text_color_for(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """Branco em fundos escuros, preto em fundos claros."""
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (255, 255, 255) if luminance < 160 else (20, 20, 20)


def _load_font(size: int):
    """Tenta carregar uma fonte default; cai no bitmap default do PIL."""
    from PIL import ImageFont
    # PIL 10+ tem default_font_size em load_default; usamos ImageFont.truetype
    # com o caminho de fontes do sistema mais provável.
    candidates = [
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in candidates:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    # Último recurso: bitmap default (não escala com size, mas funciona).
    return ImageFont.load_default()


def _wrap_text(draw, text: str, font, max_w: int) -> list[str]:
    """Quebra texto em linhas que cabem em `max_w` pixels."""
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for w in words[1:]:
        candidate = f"{current} {w}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_w:
            current = candidate
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


# ---- Output --------------------------------------------------------------

def _write_jpg(image_bytes: bytes, out_path: Path) -> None:
    """Normaliza para JPG 600x900 e escreve em `out_path`."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    # Escala mantendo aspect ratio + crop central pra 600x900.
    img = _resize_and_center_crop(img, COVER_W, COVER_H)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), format="JPEG", quality=88, optimize=True)


def _resize_and_center_crop(img, target_w: int, target_h: int):
    """Redimensiona pra cobrir target e faz crop central."""
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        # Imagem mais larga que o alvo — escala pela altura, corta laterais.
        new_h = target_h
        new_w = int(src_w * (target_h / src_h))
    else:
        new_w = target_w
        new_h = int(src_h * (target_w / src_w))
    img = img.resize((new_w, new_h))
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))
