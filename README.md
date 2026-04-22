# ReaderFree — Audiobook Reader Pessoal

Sistema para converter livros (`.txt`, `.pdf`, `.epub`) em audiobooks com TTS
open-source local e reproduzi-los no iPhone com **texto sincronizado palavra a
palavra** (estilo Natural Reader / ElevenLabs). Zero APIs pagas, zero conta
Apple Developer — o player é um **PWA** instalável pelo Safari.

## Pré-requisitos

- **Python 3.11+** (testado em 3.11 e 3.12; 3.13 pode ter incompatibilidades
  com `coqui-tts`)
- **Node.js 20+** e **pnpm 9+**
- **GPU NVIDIA com 6GB+ de VRAM** (opcional, mas recomendado). Sem GPU roda em
  CPU, porém lento (~10x mais devagar para XTTS-v2).
- **ffmpeg** no PATH (necessário para `pydub` e `whisperx`).
- **CUDA 12.x** compatível com PyTorch, se for usar GPU.

## Estrutura do monorepo

```
.
├── backend/     # Pipeline Python: extração → TTS → alinhamento → empacotamento
├── frontend/    # PWA Next.js 15: biblioteca e player com karaoke
├── library/     # Saída: um diretório por livro (MP3 + VTT + book.json)
└── scripts/     # Scripts shell (empacotar, servir, deploy) — Fase 7
```

## Backend — primeiro uso

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -e .
python pipeline.py --help
```

Gerar um audiobook a partir de um TXT (a partir da Fase 1):

```bash
python pipeline.py meu_livro.txt --output ../library/meu_livro/
```

Os modelos XTTS-v2 e WhisperX são baixados do Hugging Face na primeira
execução (~3 GB somados) e ficam em cache em `~/.cache/`.

## Frontend — primeiro uso

```bash
cd frontend
pnpm install
pnpm dev
```

Abra `http://localhost:3000`. Para testar no iPhone, exponha o dev server via
Tailscale ou deploy no Cloudflare Pages (ver Fase 7).

## Onde ficam os livros gerados

Tudo em `library/<nome-do-livro>/`:

```
library/meu_livro/
├── book.json           # Metadados + lista de capítulos
├── chapter_01.mp3      # Áudio sintetizado
├── chapter_01.vtt      # Timestamps por palavra (WebVTT)
├── chapter_01.txt      # Texto original do capítulo
└── ...
```

Para importar no PWA: zipar a pasta do livro (`scripts/package_book.sh` a
partir da Fase 7) e importar via botão "Importar livro" no app.

## Status do projeto

Em construção por fases. Fase atual: **0 — Setup**.

- [x] Fase 0 — Estrutura e esqueleto
- [ ] Fase 1 — Pipeline TXT → MP3 + VTT
- [ ] Fase 2 — Suporte a PDF e EPUB
- [ ] Fase 3 — Voice cloning polido
- [ ] Fase 4 — Frontend PWA básico
- [ ] Fase 5 — Sincronização de texto (karaoke)
- [ ] Fase 6 — Offline / service worker
- [ ] Fase 7 — Deploy e acesso do iPhone
