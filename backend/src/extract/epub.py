"""Extração de texto a partir de arquivos .epub.

Estratégia (decisão da Fase 2 — ver `docs/phase2-research.md` § 2):

1. **ebooklib** para parser do OPF e leitura do ZIP. Mantido apesar de
   pouco mantido — alternativas piores. Spine é a fonte de verdade da ordem
   de leitura.
2. **`linear="no"` ignorado por default**, com log explícito do item pulado.
   Flag `include_auxiliary=True` reverte. Captura a intenção da spec EPUB:
   itens auxiliares acessados fora da sequência (apêndices, notas).
3. **Título de capítulo via cascata**: primeiro `<h1>`, senão `<h2>`,
   senão `<title>` do HTML, senão nome do arquivo do spine.
4. **Recuperação tolerante para EPUBs mal-formados**:
   - Parser HTML via BeautifulSoup com `lxml` (modo HTML, tolerante).
   - Encoding: tenta utf-8, cp1252, latin-1 — sem `chardet`.
   - href no spine apontando para arquivo inexistente: warning + skip.
   - Aborta só se zero capítulos forem recuperáveis.
5. **Limpeza de HTML**: remove `<script>`, `<style>`, `<table>`, `<figure>`,
   tags inline de footnote (`<sup>`, `<aside epub:type="footnote">`), e
   elementos com `epub:type="footnote"`. Texto de bloco vira parágrafos
   separados por `\\n\\n`.
"""
from __future__ import annotations

import logging
import warnings
from pathlib import Path

logger = logging.getLogger(__name__)

# Tags HTML cujo conteúdo deve ser totalmente removido (não falado pelo TTS).
_DROP_TAGS = (
    "script", "style", "table", "figure", "figcaption",
    "sup",  # superscripts (típico de notas de rodapé inline)
    "head",  # já lemos title separadamente
)

# Tags de bloco que separam parágrafos. Conteúdo extraído com \n\n entre eles.
_BLOCK_TAGS = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "section")

_ENCODING_FALLBACKS = ("utf-8", "cp1252", "latin-1")


def extract(path: Path, include_auxiliary: bool = False) -> list[dict]:
    """Extrai capítulos de um EPUB.

    Args:
        path: caminho do .epub.
        include_auxiliary: se True, inclui itens do spine com `linear="no"`
            (apêndices, notas) na sequência principal. Default False.

    Returns:
        Lista de capítulos no formato ``[{"title": str, "text": str}]``,
        na ordem do spine.

    Raises:
        ValueError: nenhum capítulo recuperável (EPUB inválido ou todos
            os arquivos do spine corrompidos/ausentes).
    """
    # Imports lazy: ebooklib + bs4 carregam só aqui.
    import ebooklib
    from ebooklib import epub

    # ebooklib emite vários FutureWarnings de XML — silenciamos por leitura.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = epub.read_epub(str(path))

    spine_items = list(book.spine)  # [(idref, linear), ...]
    chapters: list[dict] = []
    skipped_aux: list[str] = []
    warnings_emitted: list[str] = []

    for idref, linear in spine_items:
        item = book.get_item_with_id(idref)
        if item is None:
            warnings_emitted.append(f"spine idref '{idref}' não encontrado no manifest")
            logger.warning("[warn] %s", warnings_emitted[-1])
            continue
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            # Imagens, css, fontes na spine não fazem sentido como capítulo.
            continue

        # Spec EPUB: linear pode ser "yes"/"no" (string) ou bool dependendo
        # da lib. Normalizamos.
        is_linear = _is_linear(linear)
        if not is_linear and not include_auxiliary:
            title = _quick_title(item) or item.get_name()
            skipped_aux.append(title)
            logger.info(
                "[skipped] %s (linear=\"no\", use --include-auxiliary para incluir)",
                title,
            )
            continue

        try:
            html_bytes = item.get_content()
        except Exception as exc:
            warnings_emitted.append(f"falha ao ler '{item.get_name()}': {exc}")
            logger.warning("[warn] %s", warnings_emitted[-1])
            continue

        html = _decode_with_fallback(html_bytes)
        if html is None:
            warnings_emitted.append(
                f"encoding ilegível em '{item.get_name()}' "
                f"(tentei {', '.join(_ENCODING_FALLBACKS)})"
            )
            logger.warning("[warn] %s", warnings_emitted[-1])
            continue

        title, text = _parse_html(html, fallback_title=_filename_title(item.get_name()))
        if not text.strip():
            # Capítulo vazio (página de separador, dedicatória trivial).
            continue
        chapters.append({"title": title, "text": text})

    if not chapters:
        msg = f"EPUB '{path.name}' não rendeu nenhum capítulo recuperável."
        if warnings_emitted:
            msg += "\n\nWarnings durante extração:\n  - " + "\n  - ".join(warnings_emitted)
        raise ValueError(msg)

    if warnings_emitted:
        logger.info("[summary] %d capítulos extraídos, %d com warnings",
                    len(chapters), len(warnings_emitted))
    if skipped_aux:
        logger.info("[summary] %d capítulos auxiliares pulados (linear=\"no\")",
                    len(skipped_aux))

    return chapters


# --- Internals ------------------------------------------------------------

def _is_linear(value) -> bool:
    """Normaliza o valor de spine `linear` (string ou bool, conforme a lib)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() != "no"
    return True  # default da spec: linear


def _decode_with_fallback(data: bytes) -> str | None:
    """Tenta decodificar bytes em string usando uma cascata de encodings.

    Retorna None se nenhum funcionar.
    """
    for enc in _ENCODING_FALLBACKS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _parse_html(html: str, fallback_title: str) -> tuple[str, str]:
    """Parse de uma página HTML do EPUB. Retorna (title, text)."""
    from bs4 import BeautifulSoup  # lazy

    # lxml em modo HTML é tolerante a tags abertas, entidades inválidas.
    soup = BeautifulSoup(html, "lxml")

    # Título: cascata h1 → h2 → <title> → fallback.
    title = (
        _first_text(soup, "h1")
        or _first_text(soup, "h2")
        or _first_text(soup, "title")
        or fallback_title
    )

    # Remove tags totalmente indesejadas (incluindo conteúdo).
    for tag_name in _DROP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elementos marcados como footnote pela spec EPUB 3.
    for tag in soup.find_all(attrs={"epub:type": True}):
        if "footnote" in tag.get("epub:type", ""):
            tag.decompose()

    # Coleta texto por blocos.
    body = soup.body or soup
    paragraphs: list[str] = []
    for el in body.find_all(_BLOCK_TAGS):
        # Se o bloco já contém outros blocos, pegamos só os filhos diretos
        # (evita duplicar — um <div> com 3 <p> dentro emite os 3 <p> separados).
        if el.find(_BLOCK_TAGS):
            continue
        text = el.get_text(separator=" ", strip=True)
        if text:
            paragraphs.append(text)

    if not paragraphs:
        # Fallback: HTML sem tags de bloco reconhecíveis. Pega tudo.
        text = body.get_text(separator=" ", strip=True)
    else:
        text = "\n\n".join(paragraphs)

    return title.strip(), text.strip()


def _first_text(soup, tag_name: str) -> str | None:
    el = soup.find(tag_name)
    if el is None:
        return None
    text = el.get_text(strip=True)
    return text or None


def _quick_title(item) -> str | None:
    """Tenta extrair título sem fazer parse HTML completo (usado no log de skip)."""
    try:
        html_bytes = item.get_content()
    except Exception:
        return None
    html = _decode_with_fallback(html_bytes)
    if html is None:
        return None
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    return (
        _first_text(soup, "h1")
        or _first_text(soup, "h2")
        or _first_text(soup, "title")
    )


def _filename_title(name: str) -> str:
    """Deriva um título legível a partir do nome do arquivo do spine."""
    stem = Path(name).stem
    cleaned = stem.replace("_", " ").replace("-", " ").strip(" .")
    return cleaned or "Sem título"
