"""ReaderFree — CLI principal do pipeline de geração de audiobooks.

Exemplos:
    # Liste as vozes disponíveis no XTTS-v2
    python pipeline.py voices

    # TXT com voz escolhida
    python pipeline.py build livro.txt --output ../library/meu_livro/ \\
        --speaker "Claribel Dervla"

    # PDF (com OCR automático se necessário)
    python pipeline.py build livro.pdf --output ../library/x/ --auto-ocr

    # EPUB (incluindo apêndices linear="no")
    python pipeline.py build livro.epub --output ../library/y/ --include-auxiliary

    # Voice cloning de arquivo (alternativa a --speaker)
    python pipeline.py build livro.txt --output ../library/x/ --voice amostra.wav

    # Smoke test sem GPU
    python pipeline.py build livro.txt --output ../library/test --mock

    # Apenas alguns capítulos
    python pipeline.py build livro.epub --output ../library/x/ --chapters-only 1,3,5-7

    python pipeline.py doctor
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows console costuma vir em cp1252 e quebra em caracteres tipo →/ç/✓.
# Força UTF-8 cedo, antes de qualquer import que use stdout.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

import click  # noqa: E402
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from src import config as cfg
from src.build import BuildCancelled, BuildProgress, build_book

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
    help="WAV/MP3 de referência para voice cloning a partir de arquivo.",
)
@click.option(
    "--speaker",
    type=str,
    default=None,
    help="Nome de um speaker interno do XTTS-v2 (recomendado). "
         "Liste opções com `python pipeline.py voices`.",
)
@click.option("--language", default=cfg.DEFAULT_LANGUAGE, show_default=True, help="Idioma do XTTS.")
@click.option(
    "--device",
    type=click.Choice(["auto", "cuda", "cpu"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--chunk-chars",
    default=cfg.DEFAULT_CHUNK_CHARS,
    show_default=True,
    type=int,
    help="Máximo de caracteres por chunk enviado ao XTTS.",
)
@click.option(
    "--chapters-only",
    default=None,
    help="Processa apenas o(s) capítulo(s). Aceita item, lista, range, ou "
         "combinações: '3', '1,3,5', '1-3', '1,3,5-7,10'.",
)
@click.option(
    "--auto-ocr",
    is_flag=True,
    help="(PDF) Roda 'ocrmypdf --skip-text --language por' antes de extrair, "
         "se ocrmypdf estiver no PATH. Default: falha cedo com instrução.",
)
@click.option(
    "--include-auxiliary",
    is_flag=True,
    help='(EPUB) Inclui capítulos com spine linear="no" (apêndices, notas). '
         "Default: pula com log explícito.",
)
@click.option(
    "--mock",
    is_flag=True,
    help="Não carrega modelos. Silêncio + VTT sintético. Valida pipeline sem GPU.",
)
@click.option("--title", default=None, help="Título do livro (default: nome do arquivo).")
@click.option("--author", default=None, help="Autor do livro.")
def build(
    input_path: Path,
    output: Path,
    voice: Path | None,
    speaker: str | None,
    language: str,
    device: str,
    chunk_chars: int,
    chapters_only: str | None,
    auto_ocr: bool,
    include_auxiliary: bool,
    mock: bool,
    title: str | None,
    author: str | None,
) -> None:
    """Gera um audiobook a partir de um .txt/.pdf/.epub.

    Wrapper Click fino sobre `src.build.build_book`. A lógica real está
    desacoplada do CLI desde a Fase 6.1 — o servidor importa a mesma
    função.
    """
    if voice is not None and speaker is not None:
        raise click.UsageError(
            "Use --voice OU --speaker, não os dois. "
            "--voice = cloning de arquivo; --speaker = voz interna do XTTS."
        )

    paths = cfg.resolve_paths()
    console.print(f"[bold]ReaderFree[/bold] → {input_path.name}")
    if mock:
        console.print("[yellow]MOCK MODE[/yellow] — sem síntese real, sem alinhamento real.")
    console.print(f"  dispositivo : {cfg.resolve_device(device)}")
    console.print(f"  chunk-chars : {chunk_chars}")
    console.print(f"  output      : {output}")
    if paths.config_file:
        console.print(f"  config      : {paths.config_file}")
    if not mock and voice is None and speaker is None:
        console.print(
            "[yellow]⚠  nenhuma voz selecionada.[/yellow] Usando o primeiro speaker "
            "interno do XTTS-v2 como fallback. Para escolher uma voz específica, "
            "passe [cyan]--speaker NOME[/cyan] (rode `python pipeline.py voices` "
            "para listar) ou [cyan]--voice arquivo.wav[/cyan] para cloning."
        )

    progress_state: dict = {}  # mantém referência a Progress task ativa por fase

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:

        def on_progress(ev: BuildProgress) -> None:
            # Para cada fase TTS, reseta a task ao mudar de capítulo.
            key = (ev.phase, ev.chapter_idx)
            if ev.phase == "tts":
                if key not in progress_state:
                    desc = f"[cyan]TTS — {ev.chapter_label or ''}"
                    progress_state[key] = progress.add_task(desc, total=ev.total)
                progress.update(progress_state[key], completed=ev.current)
            elif ev.phase in ("extract", "segment", "align", "package"):
                msg = ev.message or ev.phase
                console.log(f"[dim]{ev.phase}:[/dim] {msg}")

        try:
            book_json = build_book(
                input_path=input_path,
                output_dir=output,
                voice=voice,
                speaker=speaker,
                language=language,
                device=device,
                chunk_chars=chunk_chars,
                chapters_only=chapters_only,
                auto_ocr=auto_ocr,
                include_auxiliary=include_auxiliary,
                mock=mock,
                title=title,
                author=author,
                on_progress=on_progress,
            )
        except BuildCancelled:
            console.print("[red]Cancelado.[/red]")
            return
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc

    console.rule("[bold green]Concluído")
    console.print(f"  book.json : {output / 'book.json'}")
    console.print(f"  duração   : {book_json['duration_seconds']:.1f}s total")
    console.print(f"  capítulos : {len(book_json['chapters'])}")


@cli.command()
def voices() -> None:
    """Lista as vozes internas do XTTS-v2.

    Carrega o modelo (~10–30s no disco quente). Use o nome listado com
    `build --speaker NOME`. Cada speaker é um perfil de voz pré-computado;
    todos sintetizam pt-br corretamente apesar dos nomes em inglês.
    """
    paths = cfg.resolve_paths()
    cfg.apply_model_cache_env(paths)
    console.print("[bold]Carregando XTTS-v2...[/bold] (pode demorar na primeira vez)")
    try:
        from src.voices import list_speakers
        speakers = list_speakers()
    except ImportError:
        console.print(
            "[red]coqui-tts não instalado.[/red] "
            "Rode `pip install -e .[tts]` para usar este comando."
        )
        return
    except Exception as exc:  # pragma: no cover — rodapé operacional
        console.print(f"[red]Falha ao carregar XTTS-v2:[/red] {exc}")
        return

    console.print(f"\n[bold]{len(speakers)} vozes disponíveis:[/bold]\n")
    # Imprime em duas colunas para listas longas.
    half = (len(speakers) + 1) // 2
    left, right = speakers[:half], speakers[half:]
    width = max((len(s) for s in left), default=0) + 2
    for i in range(half):
        l = left[i]
        r = right[i] if i < len(right) else ""
        console.print(f"  {l.ljust(width)}  {r}")
    console.print(
        "\nUse com: [cyan]python pipeline.py build livro.txt "
        "--output ../library/x/ --speaker NOME[/cyan]"
    )


@cli.command()
def doctor() -> None:
    """Verifica dependências (Python, ffmpeg, torch/CUDA, paths)."""
    import shutil

    paths = cfg.resolve_paths()
    console.print("[bold]ReaderFree doctor[/bold]")
    console.print(f"  Python    : {sys.version.split()[0]}")
    ffmpeg = shutil.which("ffmpeg")
    console.print(f"  ffmpeg    : {ffmpeg or '[red]não encontrado[/red]'}")
    try:
        import torch  # noqa: PLC0415

        cuda = torch.cuda.is_available()
        console.print(f"  torch     : {torch.__version__} (CUDA: {cuda})")
    except ImportError:
        console.print(
            "  torch     : [yellow]não instalado[/yellow] "
            "(ok para --mock; para síntese real rode `pip install -e .[tts]`)"
        )
    try:
        import TTS  # noqa: F401, PLC0415

        console.print("  coqui-tts : [green]disponível[/green]")
    except ImportError:
        console.print("  coqui-tts : [yellow]não instalado[/yellow]")
    try:
        import whisperx  # noqa: F401, PLC0415

        console.print("  whisperx  : [green]disponível[/green]")
    except ImportError:
        console.print("  whisperx  : [yellow]não instalado[/yellow]")
    console.print(f"  library   : {paths.library_dir}")
    console.print(f"  models    : {paths.models_dir}")
    console.print(f"  config    : {paths.config_file or '[não existe]'}")
    console.print(
        "\n[dim]Lembrete: `build` sem --speaker/--voice usa o primeiro speaker "
        "interno do XTTS como fallback. Para escolher uma voz, rode "
        "`python pipeline.py voices` e use --speaker NOME.[/dim]"
    )


if __name__ == "__main__":
    cli()
