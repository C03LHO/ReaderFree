# ReaderFree — Audiobook Reader Pessoal

Sistema para converter livros (`.txt`, `.pdf`, `.epub`) em audiobooks com TTS
open-source local e reproduzi-los no iPhone com **texto sincronizado palavra a
palavra** (estilo Natural Reader / ElevenLabs). Zero APIs pagas, zero conta
Apple Developer — o player é um **PWA** instalável pelo Safari.

## Pré-requisitos

- **Python 3.11** (ver "Por que Python 3.11 e não 3.13" abaixo)
- **Node.js 20+** e **pnpm 9+**
- **Next.js 16** (vem via `create-next-app@latest`; o manifesto PWA é um
  `app/manifest.ts` type-safe, não `public/manifest.json`)
- **GPU NVIDIA com 6GB+ de VRAM** (opcional, mas recomendado). Sem GPU roda em
  CPU, porém lento (~10x mais devagar para XTTS-v2).
- **ffmpeg** no PATH (necessário para `pydub` e `whisperx`).
- **CUDA 12.x** compatível com PyTorch, se for usar GPU.

## Estrutura do monorepo

```
.
├── backend/     # Pipeline Python: extração → TTS → alinhamento → empacotamento
├── frontend/    # PWA Next.js 16: biblioteca e player com karaoke
├── library/     # Saída: um diretório por livro (MP3 + VTT + book.json)
└── scripts/     # Scripts shell (empacotar, servir, deploy) — Fase 7
```

## Backend — primeiro uso

Usa `coqui-tts` + `whisperx`, que arrastam `torch`, `librosa`, e extensões
C. **Rode em Python 3.11**, não 3.13 — ver seção abaixo.

```bash
cd backend

# Crie o venv com Python 3.11 especificamente:
#   Windows:  py -3.11 -m venv venv
#   Linux/Mac: python3.11 -m venv venv
py -3.11 -m venv venv

# Ative:
#   Windows PowerShell:  .\venv\Scripts\Activate.ps1
#   Windows bash/git bash: source venv/Scripts/activate
#   Linux/Mac:            source venv/bin/activate
source venv/Scripts/activate

pip install -e .
python pipeline.py --help
```

### Síntese real (com modelos): instalar `[tts]` e PyTorch CUDA

Para usar TTS real (sem `--mock`), instale o extra `[tts]` e — se for usar GPU
NVIDIA — reinstale o `torch`/`torchaudio` apontando para o índice CUDA do
PyTorch. As versões pinadas no `pyproject.toml` (`torch==2.5.1`,
`transformers==4.40.2`, `setuptools==69.5.1`, `coqui-tts==0.24.3`,
`whisperx==3.3.1`) foram validadas juntas em GPU RTX 4060 Ti (abr/2026).

```bash
# Instala todas as deps de TTS + alinhamento (CPU build do torch).
pip install -e ".[tts]"

# Para GPU NVIDIA (CUDA 12.1): reinstala torch e torchaudio do índice CUDA.
# Sem este passo o coqui-tts roda em CPU (~10x mais lento).
pip install --index-url https://download.pytorch.org/whl/cu121 \
    --force-reinstall torch==2.5.1 torchaudio==2.5.1

# Verifique:
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
# Saída esperada: True 12.1
```

**Por que cada constraint existe** (cada uma resolveu um conflito real durante
a validação):

- `transformers==4.40.2` — a 4.41+ removeu `LogitsWarper`, importado pelo
  `coqui-tts 0.24.3`.
- `setuptools==69.5.1` — a 70+ removeu `pkg_resources` por padrão; o
  `whisperx 3.3.1` ainda usa internamente.
- `torch==2.5.1` — versão sob a qual o stack inteiro
  (coqui-tts + whisperx + transformers 4.40) bate.

Gerar um audiobook a partir de um TXT (a partir da Fase 1):

```bash
# Recomendado: passe uma amostra de voz (15–30s, WAV ou MP3) para voice cloning.
python pipeline.py build meu_livro.txt --output ../library/meu_livro/ --voice voices/minha_voz.wav

# Smoke test sem amostra — usa um speaker interno do XTTS (qualidade varia).
python pipeline.py build meu_livro.txt --output ../library/meu_livro/

# Sem GPU ou sem torch instalado: modo mock gera áudio silencioso + VTT sintético
# para validar o pipeline de dados.
python pipeline.py build meu_livro.txt --output ../library/meu_livro/ --mock
```

### Voice cloning — qualidade

**Recomendação forte:** sempre passe `--voice` apontando para uma amostra de
voz de 15–30 segundos, gravada em ambiente silencioso, 24 kHz mono. A Fase 3
inclui scripts para gravar e preparar essa amostra (`backend/record_voice.py`,
`backend/prepare_reference.py`).

Sem `--voice`, o XTTS-v2 cai no primeiro speaker interno do modelo (tipo
"Claribel Dervla"). Isso funciona para **smoke test** (verificar que o
pipeline roda), mas a qualidade/consistência varia muito entre execuções e
entre chunks. Não use para audiobooks "de verdade".

Os modelos XTTS-v2 e WhisperX são baixados do Hugging Face na primeira
execução (~3 GB somados) e ficam em cache conforme as env vars resolvidas em
`backend/src/config.py` (default: `%LOCALAPPDATA%\ReaderFree\models\` no
Windows).

## Por que Python 3.11 e não 3.13

`coqui-tts` depende de `torch`, `librosa`, `TTS` internals e outras libs com
extensões C/wheel que historicamente travam em Python 3.13 (wheels ausentes
para a ABI nova, imports quebrados, erros obscuros em _collections_abc etc.).
Python 3.11 é a versão de suporte mais testada para esse stack e o que o
próprio ecossistema de ML ainda trata como baseline. Ficamos em 3.11 até que
o ecossistema se estabilize em 3.13+.

## Frontend — primeiro uso

```bash
cd frontend
pnpm install
pnpm dev
```

Abra `http://localhost:3000`. Para testar no iPhone, exponha o dev server via
Tailscale ou deploy no Cloudflare Pages (ver Fase 7).

### Service worker / PWA

Usamos **[Serwist](https://serwist.pages.dev/)** (`@serwist/next` + `serwist`),
não `next-pwa`. Razão: `next-pwa` está sem release desde 2022 e o doc oficial
do Next 16 indica Serwist. O service worker vive em `src/app/sw.ts` e é
pré-compilado pelo bundler — configurado na Fase 6.

## Onde ficam os livros gerados

Tudo em `library/<nome-do-livro>/`:

```
library/meu_livro/
├── book.json                     # Metadados + lista de capítulos
├── chapter_01.mp3                # Áudio sintetizado
├── chapter_01.vtt                # Timestamps por palavra (WebVTT)
├── chapter_01.txt                # Texto original do capítulo
├── chapter_05_part_01.mp3        # Capítulos longos são divididos em partes
├── chapter_05_part_01.vtt        # (Fase 2+, ver `docs/phase2-research.md` § 3)
└── ...
```

### Schema do `book.json`

```jsonc
{
  "id": "memorias-postumas",                  // slug do título
  "title": "Memórias Póstumas de Brás Cubas",
  "author": "Machado de Assis",               // string | null
  "created_at": "2026-04-25T12:34:56+00:00",  // ISO 8601 UTC
  "duration_seconds": 8175.6,                 // soma de todos os capítulos
  "mock": false,                              // true se gerado com --mock
  "chapters": [
    {
      "id": "memorias-postumas-01",
      "title": "Ao leitor",
      "mp3_path": "chapter_01.mp3",
      "vtt_path": "chapter_01.vtt",
      "text_path": "chapter_01.txt",
      "duration_seconds": 45.6,
      "word_count": 95
      // part/total_parts ausentes = capítulo único
    },
    {
      "id": "memorias-postumas-02",           // mesmo id em todas as partes
      "title": "Capítulo Longo",
      "mp3_path": "chapter_02_part_01.mp3",
      "vtt_path": "chapter_02_part_01.vtt",
      "text_path": "chapter_02_part_01.txt",
      "duration_seconds": 2700.0,
      "word_count": 8000,
      "part": 1,                              // só presentes em capítulos
      "total_parts": 3                        // divididos (>9000 palavras)
    }
    // ... part 2/3, part 3/3
  ]
}
```

Capítulos divididos compartilham `id` e `title`; o que diferencia é o par
`(part, total_parts)`. Capítulos não-divididos não trazem esses campos
(ausência = capítulo único). Frontend usa o par para desenhar "Parte 2 de 3"
no header do reader e para encadear playback automático.

Para importar no PWA: zipar a pasta do livro (`scripts/package_book.sh` a
partir da Fase 7) e importar via botão "Importar livro" no app.

## Status do projeto

Em construção por fases.

- [x] Fase 0 — Estrutura e esqueleto
- [x] Fase 1 — Pipeline TXT → MP3 + VTT (validado em GPU RTX 4060 Ti, abr/2026 — voz natural em pt-BR, deriva WhisperX <150ms, ~1min40s para o excerto de Brás Cubas)
- [x] Fase 1.5 — `book.json` com `part`/`total_parts` (preparação para capítulos divididos)
- [x] Fase 2 — Suporte a PDF e EPUB (implementada; validação end-to-end com mock; aguardando validação real em GPU)
- [ ] Fase 3 — Voice cloning polido
- [ ] Fase 4 — Frontend PWA básico
- [ ] Fase 5 — Sincronização de texto (karaoke)
- [ ] Fase 6 — Offline / service worker
- [ ] Fase 7 — Deploy e acesso do iPhone
