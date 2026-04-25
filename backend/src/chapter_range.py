"""Parsing da flag `--chapters-only`.

Aceita lista, range, e combinações. Função pura, sem efeito colateral.

Exemplos:
    parse_chapter_range("3", total=10)        -> {3}
    parse_chapter_range("1,3,5", total=10)    -> {1, 3, 5}
    parse_chapter_range("1-3", total=10)      -> {1, 2, 3}
    parse_chapter_range("1,3,5-7,10", 10)     -> {1, 3, 5, 6, 7, 10}
    parse_chapter_range("1-3,2-4", 10)        -> {1, 2, 3, 4}   # sobreposições deduplicadas
    parse_chapter_range(" 1 , 3 - 5 ", 10)    -> {1, 3, 4, 5}   # espaços toleráveis

Erros (todos com `ValueError` e mensagem clara para o usuário):
    "5-3"          range invertido
    "0", "-1"      capítulos numerados a partir de 1
    "abc", "1-a"   lixo não-numérico
    "99" total=40  fora do range do livro
"""
from __future__ import annotations


def parse_chapter_range(spec: str, total: int) -> set[int]:
    """Resolve uma spec textual em um conjunto de índices de capítulo (1-based).

    Args:
        spec: string com itens separados por vírgula. Cada item é um número
            (`5`) ou um range fechado (`5-7`, equivale a `{5, 6, 7}`).
        total: número total de capítulos disponíveis no livro. Usado para
            validar o limite superior.

    Returns:
        set[int] com os índices selecionados, sem duplicatas.

    Raises:
        ValueError: spec malformada, range invertido, capítulo fora do range,
            ou capítulo ≤ 0.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("--chapters-only vazio. Exemplo: '1,3,5-7'.")
    if total < 1:
        raise ValueError(f"livro sem capítulos (total={total}).")

    selected: set[int] = set()
    for raw_item in spec.split(","):
        item = raw_item.strip()
        if not item:
            # vírgula extra tipo "1,,3" — ignora silenciosamente
            continue
        if "-" in item:
            selected |= _parse_range(item, total)
        else:
            selected.add(_parse_single(item, total))

    if not selected:
        raise ValueError(f"--chapters-only '{spec}' não selecionou nenhum capítulo.")
    return selected


def _parse_single(item: str, total: int) -> int:
    try:
        n = int(item)
    except ValueError as exc:
        raise ValueError(
            f"--chapters-only: '{item}' não é um número de capítulo válido."
        ) from exc
    _validate_in_range(n, total, item)
    return n


def _parse_range(item: str, total: int) -> set[int]:
    parts = item.split("-")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(
            f"--chapters-only: range '{item}' malformado. Use 'N-M' com N ≤ M."
        )
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip())
    except ValueError as exc:
        raise ValueError(
            f"--chapters-only: range '{item}' contém valor não-numérico."
        ) from exc
    if start > end:
        raise ValueError(
            f"--chapters-only: range invertido '{item}' (use {end}-{start})."
        )
    _validate_in_range(start, total, item)
    _validate_in_range(end, total, item)
    return set(range(start, end + 1))


def _validate_in_range(n: int, total: int, context: str) -> None:
    if n < 1:
        raise ValueError(
            f"--chapters-only: '{context}' usa capítulo {n} (capítulos começam em 1)."
        )
    if n > total:
        raise ValueError(
            f"--chapters-only: capítulo {n} fora do range "
            f"(livro tem {total} capítulo{'s' if total != 1 else ''})."
        )
