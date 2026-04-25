"""ReaderFree — CLI principal do pipeline de geração de audiobooks.

Exemplos:
    # TXT
    python pipeline.py build livro.txt --output ../library/meu_livro/

    # PDF (com OCR automático se necessário)
    python pipeline.py build livro.pdf --output ../library/x/ --auto-ocr

    # EPUB (incluindo apêndices linear="no")
    python pipeline.py build livro.epub --output ../library/y/ --include-auxiliary

    # Smoke test sem GPU
    python pipeline.py build livro.txt --output ../library/test --mock

    # Apenas alguns capítulos
    python pipeline.py build livro.epub --output ../library/x/ --chapters-only 1,3,5-7

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

from src import align, chapter_range, chapter_split, config as cfg, package, sanitize, segment, tts

console = Console()


def _extract(
    input_path: Path,
    auto_ocr: bool = False,
    include_auxiliary: bool = False,
) -> list[dict]:
    """Dispatch por extensão.

    Args:
        input_path: arquivo de entrada (.txt, .pdf, .epub).
        auto_ocr: passado para o extractor de PDF (ignorado nos demais).
        include_auxiliary: passado para o extractor de EPUB (ignorado nos demais).
    """
    ext = input_path.suffix.lower()
    if ext == ".txt":
        from src.extract import txt as extractor

        return extractor.extract(input_path)
    if ext == ".pdf":
        from src.extract import pdf as extractor

        try:
            return extractor.extract(input_path, auto_ocr=auto_ocr)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
    if ext == ".epub":
        from src.extract import epub as extractor

        try:
            return extractor.extract(input_path, include_auxiliary=include_auxiliary)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
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

    chapters = _extract(input_path, auto_ocr=auto_ocr, include_auxiliary=include_auxiliary)

    if chapters_only:
        try:
            selected = chapter_range.parse_chapter_range(chapters_only, total=len(chapters))
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        chapters = [c for i, c in enumerate(chapters, start=1) if i in selected]
        if not chapters:
            raise click.UsageError(f"Nenhum capítulo casou com '{chapters_only}'.")

    # Sanitização pré-TTS + divisão de capítulos longos.
    # Mantemos o índice original do capítulo (1-based) para cada parte
    # produzida, para nomear arquivos e o `id` no book.json.
    parts: list[tuple[int, dict]] = []
    for idx, chapter in enumerate(chapters, start=1):
        chapter["text"] = sanitize.sanitize_for_tts(chapter["text"])
        for part in chapter_split.split_chapter_if_needed(chapter):
            parts.append((idx, part))

    n_chapters = len(chapters)
    n_parts = len(parts)
    if n_parts > n_chapters:
        console.print(
            f"  capítulos   : {n_chapters} ({n_parts - n_chapters} dividido(s) "
            f"em partes — total {n_parts} arquivos)"
        )
    else:
        console.print(f"  capítulos   : {n_chapters}")

    output.mkdir(parents=True, exist_ok=True)

    book_title = title or input_path.stem.replace("_", " ").strip()
    book_id = package.slugify(book_title) or uuid.uuid4().hex[:8]
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    synth_fn = tts.synthesize_mock if mock else tts.synthesize
    align_fn = align.align_mock if mock else align.align

    total_duration = 0.0
    chapter_entries: list[dict] = []

    for chapter_idx, part in parts:
        ch_title: str = part["title"]
        ch_text: str = part["text"]
        is_split = "total_parts" in part

        if is_split:
            stem = f"chapter_{chapter_idx:02d}_part_{part['part']:02d}"
            header = f"Capítulo {chapter_idx:02d} ({part['part']}/{part['total_parts']}) — {ch_title}"
        else:
            stem = f"chapter_{chapter_idx:02d}"
            header = f"Capítulo {chapter_idx:02d} — {ch_title}"
        console.rule(header)

        sentences = segment.split_sentences(ch_text, language="portuguese")
        chunks = segment.group_into_chunks(sentences, max_chars=chunk_chars)
        console.print(f"  {len(sentences)} sentenças → {len(chunks)} chunks")

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
        console.print(
            f"  [green]✓[/green] {mp3_path.name} — {duration:.2f}s, "
            f"{len(words)} palavras"
        )

        entry = {
            "id": f"{book_id}-{chapter_idx:02d}",
            "title": ch_title,
            "mp3_path": mp3_path.name,
            "vtt_path": vtt_path.name,
            "text_path": txt_path.name,
            "duration_seconds": round(duration, 3),
            "word_count": len(words),
        }
        if is_split:
            entry["part"] = part["part"]
            entry["total_parts"] = part["total_parts"]
        chapter_entries.append(entry)

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
