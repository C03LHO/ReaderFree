"""ReaderFree — CLI principal do pipeline de geração de audiobooks.

Exemplos:
    python pipeline.py build livro.txt --output ../library/meu_livro/
    python pipeline.py build livro.txt --output ../library/test --mock
    python pipeline.py doctor
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
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

from src import align, config as cfg, package, segment, tts

console = Console()


def _extract(input_path: Path) -> list[dict]:
    """Dispatch por extensão. Fase 1 implementa .txt; PDF/EPUB na Fase 2."""
    ext = input_path.suffix.lower()
    if ext == ".txt":
        from src.extract import txt as extractor

        return extractor.extract(input_path)
    if ext == ".pdf":
        from src.extract import pdf as extractor  # noqa: F401

        raise click.UsageError("Suporte a PDF entra na Fase 2.")
    if ext in {".epub"}:
        from src.extract import epub as extractor  # noqa: F401

        raise click.UsageError("Suporte a EPUB entra na Fase 2.")
    raise click.UsageError(f"Extensão não suportada: {ext}. Use .txt, .pdf ou .epub.")


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
    help="Processa apenas o(s) capítulo(s): '1' ou '1,3,5' (Fase 2+).",
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
    language: str,
    device: str,
    chunk_chars: int,
    chapters_only: str | None,
    mock: bool,
    title: str | None,
    author: str | None,
) -> None:
    """Gera um audiobook a partir de um .txt/.pdf/.epub."""
    paths = cfg.resolve_paths()
    if not mock:
        cfg.apply_model_cache_env(paths)

    console.print(f"[bold]ReaderFree[/bold] → {input_path.name}")
    if mock:
        console.print("[yellow]MOCK MODE[/yellow] — sem síntese real, sem alinhamento real.")
    console.print(f"  dispositivo : {cfg.resolve_device(device)}")
    console.print(f"  chunk-chars : {chunk_chars}")
    console.print(f"  output      : {output}")
    if paths.config_file:
        console.print(f"  config      : {paths.config_file}")
    if not mock and voice is None:
        console.print(
            "[yellow]⚠  nenhum --voice passado.[/yellow] Usando speaker interno do XTTS-v2 "
            "(fallback para o primeiro speaker do modelo, e.g. 'Claribel Dervla'). "
            "Qualidade varia e é só para smoke test — passe --voice amostra.wav para "
            "voice cloning (15–30s de áudio limpo)."
        )

    chapters = _extract(input_path)
    if chapters_only:
        selected = {int(x.strip()) for x in chapters_only.split(",") if x.strip()}
        chapters = [c for i, c in enumerate(chapters, start=1) if i in selected]
        if not chapters:
            raise click.UsageError(f"Nenhum capítulo casou com '{chapters_only}'.")
    console.print(f"  capítulos   : {len(chapters)}")
    output.mkdir(parents=True, exist_ok=True)

    book_title = title or input_path.stem.replace("_", " ").strip()
    book_id = package.slugify(book_title) or uuid.uuid4().hex[:8]
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    synth_fn = tts.synthesize_mock if mock else tts.synthesize
    align_fn = align.align_mock if mock else align.align

    total_duration = 0.0
    chapter_entries: list[dict] = []

    for idx, chapter in enumerate(chapters, start=1):
        ch_title: str = chapter["title"]
        ch_text: str = chapter["text"]
        console.rule(f"Capítulo {idx:02d} — {ch_title}")

        sentences = segment.split_sentences(ch_text, language="portuguese")
        chunks = segment.group_into_chunks(sentences, max_chars=chunk_chars)
        console.print(f"  {len(sentences)} sentenças → {len(chunks)} chunks")

        stem = f"chapter_{idx:02d}"
        wav_path = output / f"{stem}.wav"
        mp3_path = output / f"{stem}.mp3"
        vtt_path = output / f"{stem}.vtt"
        txt_path = output / f"{stem}.txt"

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            label = "[cyan]TTS (mock)" if mock else "[cyan]TTS (XTTS-v2)"
            task = progress.add_task(label, total=len(chunks))

            def _tick(done: int, total: int) -> None:  # closure captura `task`
                progress.update(task, completed=done)

            synth_fn(
                chunks=chunks,
                output_wav=wav_path,
                voice=voice,
                language=language,
                device=device,
                sample_rate=cfg.TTS_SAMPLE_RATE,
                progress_cb=_tick,
            )

        with console.status("[cyan]Convertendo WAV → MP3..."):
            package.wav_to_mp3(wav_path, mp3_path, bitrate=cfg.MP3_BITRATE)
        wav_path.unlink(missing_ok=True)

        align_label = "[cyan]Alinhamento (mock)" if mock else "[cyan]Alinhando com WhisperX"
        with console.status(align_label):
            words = align_fn(mp3_path, ch_text, language=language, device=device)

        package.write_vtt(words, vtt_path)
        package.write_txt(ch_text, txt_path)

        duration = package.audio_duration_seconds(mp3_path)
        total_duration += duration
        console.print(f"  [green]✓[/green] {mp3_path.name} — {duration:.2f}s, {len(words)} palavras")

        chapter_entries.append(
            {
                "id": f"{book_id}-{idx:02d}",
                "title": ch_title,
                "mp3_path": mp3_path.name,
                "vtt_path": vtt_path.name,
                "text_path": txt_path.name,
                "duration_seconds": round(duration, 3),
                "word_count": len(words),
            }
        )

    package.write_book_json(
        book_id=book_id,
        title=book_title,
        author=author,
        created_at=created_at,
        duration_seconds=total_duration,
        chapters=chapter_entries,
        output_dir=output,
        mock=mock,
    )
    console.rule("[bold green]Concluído")
    console.print(f"  book.json : {output / 'book.json'}")
    console.print(f"  duração   : {total_duration:.1f}s total")


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
        "\n[dim]Lembrete: `build` sem --voice usa speaker interno do XTTS "
        "(qualidade inconsistente). Para voice cloning, forneça uma amostra "
        "WAV/MP3 de 15–30s via --voice.[/dim]"
    )


if __name__ == "__main__":
    cli()
