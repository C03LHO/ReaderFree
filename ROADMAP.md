# Roadmap do ReaderFree

Plano por fases. Cada fase termina com um entregável testável antes de avançar.

---

## ✅ Fase 0 — Estrutura e esqueleto

Monorepo, CLI esqueleto, frontend Next.js 16 com PWA manifest, .gitignore,
README. Nada gera áudio ainda.

## ✅ Fase 1 — Pipeline TXT → MP3 + VTT

- `extract/txt.py` lê e normaliza TXT.
- `segment.py` quebra em sentenças (NLTK pt) e agrupa em chunks ≤N chars.
- `tts.py` sintetiza via XTTS-v2 (lazy import de torch/TTS).
- `align.py` alinha com WhisperX (forced alignment com texto conhecido).
- `package.py` escreve MP3 (pydub/ffmpeg), VTT palavra-a-palavra, `book.json`.
- **`--mock`** substitui TTS e alinhador por stubs determinísticos: silêncio
  proporcional (~15 chars/seg) e distribuição uniforme de palavras. Valida o
  pipeline de dados em máquinas sem GPU/torch.
- Testes de unidade: `segment` (7), `package/VTT` (6), `extract/txt` (5) — 18
  testes rodam sem torch.

## ⬜ Fase 2 — Suporte a PDF e EPUB

- `extract/pdf.py`: `pypdf`. Detecta capítulos via outline/bookmarks. Avisa e
  sugere `ocrmypdf` se não houver camada de texto.
- `extract/epub.py`: `ebooklib` + `bs4`. Um capítulo por arquivo HTML do
  spine; título via primeiro `<h1>`/`<h2>`.
- `book.json` passa a suportar múltiplos capítulos.
- `--chapters-only 1,3,5` para iteração rápida.
- Teste com "Memórias Póstumas de Brás Cubas" (domínio público).

## ⬜ Fase 3 — Voice cloning polido

- `backend/record_voice.py`: grava 30s via `sounddevice`, salva 24kHz mono,
  valida SNR/clipping.
- `backend/prepare_reference.py`: recebe WAV/MP3/MP4, resample/trim/normaliza
  para amostra limpa de 15–30s.
- README com fluxo de gravação.

## ⬜ Fase 4 — Frontend PWA: biblioteca e player

- Ingestão: (A) upload de ZIP do livro (jszip → IndexedDB) e (B) URL do
  `book.json` remoto.
- Tela biblioteca: grid de livros com título/autor/duração/progresso.
- Tela reader: cabeçalho, área de texto scrollável, barra com play/pause,
  ±15s, velocidade (0.75x–2x), progresso do capítulo.
- `<audio>` HTML5 + **Media Session API** para controles na tela de bloqueio
  do iPhone.
- Estado persistido em IndexedDB (`idb`): livros, posição, velocidade.

## ⬜ Fase 5 — Sincronização de texto (karaoke)

- `lib/vtt.ts`: parser WebVTT → `WordCue[]`.
- Binding: `requestAnimationFrame` durante play, busca binária pelo cue ativo.
- `TextViewer`: spans por palavra com `data-word-index`. Highlight âmbar na
  ativa, cinza nas já-lidas. Auto-scroll com debounce.
- Tap na palavra pula o áudio (`audio.currentTime = cue.start`).
- Modos "só áudio" / "só texto" / "ambos".
- Virtualização com `react-window` para capítulos >2000 palavras.

## ⬜ Fase 6 — Offline / service worker

- **Serwist** (`@serwist/next` + `serwist`) com `src/app/sw.ts`.
- Cache: app (CacheFirst), MP3/VTT/TXT (CacheFirst com limite), `book.json`
  remoto (NetworkFirst).
- Indicador "offline" no header.
- Tela "downloads": tamanho em cache, limpar cache por livro.
- Testar em modo avião com o app instalado na home screen do iPhone.

## ⬜ Fase 7 — Deploy e acesso do iPhone

Três caminhos documentados:

- **(A) AirDrop + Cloudflare Pages**: PC gera, zipa, AirDrop pro iPhone,
  importa no PWA (hospedado no CF Pages).
- **(B) Cloudflare Pages + iCloud Drive**: livros no iCloud, importa do
  Files.app dentro do PWA.
- **(C) Tailscale + servidor local**: `python -m http.server` em `library/`,
  PWA em modo "URL do manifesto".

Scripts em `scripts/`:

- `package_book.sh` — zipa `library/X/`.
- `serve_library.sh` — HTTP com CORS habilitado.
- `deploy_frontend.sh` — build + deploy CF Pages.

## ⬜ Fase 7.5 — Empacotamento desktop (Windows)

Objetivo: instalador pequeno (~50–100 MB) que qualquer pessoa executa em
máquina Windows limpa e usa. **Não monolítico PyInstaller**; Python embeddable
+ deps instaladas no primeiro uso + modelos baixados sob demanda.

### Estrutura

```
scripts/
├── build_installer.ps1         # Master script: baixa Python embed, empacota, invoca Inno Setup
├── installer/
│   ├── ReaderFree.iss          # Script Inno Setup
│   ├── LICENSE.rtf
│   └── icons/ReaderFree.ico
└── bootstrap/
    ├── bootstrap.py            # Primeira execução: `pip install -e .[tts]` dentro do embed
    └── launcher.py             # Entry point: abre PyWebview com o frontend
```

### Pipeline do instalador (`build_installer.ps1`)

1. **Download** Python embeddable 3.11 (`python-3.11.x-embed-amd64.zip`).
2. Descompacta em `dist/python-embed/`.
3. Remove `._pth` restritivo e habilita `site` (necessário para `pip`).
4. Baixa `get-pip.py`, instala pip no embed.
5. Copia `backend/` para `dist/app/backend/`.
6. Roda `pnpm build && pnpm next export` em `frontend/` → copia `out/` para
   `dist/app/frontend/`.
7. Copia `bootstrap.py` e `launcher.py` para `dist/app/`.
8. Invoca Inno Setup (`ISCC.exe ReaderFree.iss`) → gera
   `dist/ReaderFree-Setup.exe`.

### Comportamento do instalador

- Pede destino (default `%LOCALAPPDATA%\ReaderFree\`).
- Extrai Python embed + `app/`.
- Cria atalhos: menu Iniciar + área de trabalho, apontando para
  `ReaderFree.exe` (launcher).
- Registra em "Adicionar ou Remover Programas".
- Desinstalador remove `%LOCALAPPDATA%\ReaderFree\` inteiro, incluindo cache.

### Primeira execução (`bootstrap.py`)

1. Verifica se `venv/` interno tem as deps `[tts]` instaladas.
2. Se não: janela Tk/PyWebview "Instalando dependências (primeira vez, pode
   demorar 5–10 min)" com barra de progresso, roda `python -m pip install -e
   .[tts]`.
3. Verifica se modelos XTTS/WhisperX estão em `%LOCALAPPDATA%\ReaderFree\models\`.
4. Se não: aviso "Primeira geração baixará ~5GB. Continuar?" — baixa na
   primeira `build` real, não na instalação.
5. Chama `launcher.py`.

### Launcher (`launcher.py`)

- Abre janela PyWebview 1200×800 apontando para `file://dist/app/frontend/index.html`.
- Expõe API Python para o frontend via `webview.expose()`:
  - `pickFile()` → abre dialog nativo.
  - `generateBook(input_path, voice, options)` → chama `pipeline.build` em
    subprocesso, stream de progresso via window.postMessage.
  - `openLibraryFolder()` → `explorer.exe %LOCALAPPDATA%\ReaderFree\library\`.
- Se PyWebview falhar, fallback Tkinter minimalista (mesmo set de ações).

### Requisitos do código que precisam estar em ordem ANTES da Fase 7.5

Estes foram implementados preventivamente:

- ✅ Paths via env/config.toml, sem hardcode de `~/` ou CWD. Ver
  `backend/src/config.py`.
- ✅ Versões fixadas (`==`) no `pyproject.toml`. O instalador depende dessa
  lista reprodutivelmente.
- ✅ Imports lazy (`torch`, `TTS`, `whisperx` só dentro de funções). Startup
  do CLI e do bootstrap não espera GPU subir.

### Testes

- VM Windows 11 limpa (Hyper-V ou VirtualBox).
- Instalar sem GPU: bootstrap deve rodar, CLI `doctor` deve funcionar, gerar
  livro com `--mock` deve funcionar.
- Instalar com GPU NVIDIA: geração real deve funcionar pós-download de
  modelos.
- Desinstalar: `%LOCALAPPDATA%\ReaderFree\` completamente removido.

## ⬜ Fase 8 — Polimento (backlog)

Só se 0–7.5 estiverem sólidas.

- Bookmarks.
- Highlight manual + export markdown.
- Multi-idioma no mesmo livro (autodetect por capítulo).
- Dicionário de pronúncia custom (aplicado antes do TTS).
- Regenerar frase isolada sem reprocessar livro.
- Multi-speaker (narrador + diálogos).
