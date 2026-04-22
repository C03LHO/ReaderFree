"""ReaderFree — CLI principal do pipeline de geração de audiobooks.

Uso básico (a partir da Fase 1):
    python pipeline.py livro.txt --output ../library/meu_livro/

Este arquivo é apenas o ponto de entrada: a lógica vive em `src/`.
"""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """ReaderFree — pipeline de audiobooks com TTS local + alinhamento por palavra."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Diretório de saída (será criado se não existir).",
)
@click.option(
    "--voice",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="WAV de referência para voice cloning (opcional).",
)
@click.option("--language", default="pt", show_default=True, help="Idioma alvo do XTTS.")
@click.option(
    "--device",
    type=click.Choice(["auto", "cuda", "cpu"]),
    default="auto",
    show_default=True,
    help="Dispositivo para TTS/alinhamento.",
)
@click.option(
    "--chunk-chars",
    default=250,
    show_default=True,
    type=int,
    help="Tamanho máximo em caracteres de cada chunk enviado ao XTTS.",
)
@click.option(
    "--chapters-only",
    default=None,
    help="Processa apenas o(s) capítulo(s) especificado(s), ex: '1' ou '1,3,5' (Fase 2+).",
)
def build(
    input_path: Path,
    output: Path,
    voice: Path | None,
    language: str,
    device: str,
    chunk_chars: int,
    chapters_only: str | None,
) -> None:
    """Gera um audiobook a partir de um .txt/.pdf/.epub."""
    console.print(
        "[yellow]Fase 0 — esqueleto apenas.[/yellow] "
        "A lógica de build será implementada na Fase 1."
    )
    console.print(f"  input       = {input_path}")
    console.print(f"  output      = {output}")
    console.print(f"  voice       = {voice}")
    console.print(f"  language    = {language}")
    console.print(f"  device      = {device}")
    console.print(f"  chunk-chars = {chunk_chars}")
    console.print(f"  chapters    = {chapters_only}")


@cli.command()
def doctor() -> None:
    """Verifica dependências (GPU, ffmpeg, modelos) — a implementar na Fase 1."""
    console.print("[yellow]doctor: não implementado ainda.[/yellow]")


if __name__ == "__main__":
    cli()
