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
- Testes de unidade: 27 (segment, package/VTT, extract/txt, config, mock
  regression) — rodam sem torch.

**Validação real (abr/2026, GPU RTX 4060 Ti, Windows 11):** voz XTTS-v2 saiu
natural em pt-BR; alinhamento WhisperX dentro do critério (<150 ms de deriva);
geração do excerto de Brás Cubas em ~1 min 40 s na GPU. Conflitos de
dependências resolvidos e pinados — ver notas no `backend/pyproject.toml`
(transformers 4.40.2, setuptools 69.5.1, torch 2.5.1).

## ✅ Fase 1.5 — `book.json` com `part`/`total_parts`

Preparação de schema para capítulos divididos (Fase 2 vai gerar splits quando
um capítulo passar de ~8000 palavras — ver `docs/phase2-research.md` § 3).

- `package.write_book_json` aceita `part`/`total_parts` opcionais por capítulo.
  Quando `None`, os campos não aparecem no JSON (ausência = capítulo único, não
  `null`).
- Teste novo cobrindo capítulo dividido em 3 partes + capítulo não-dividido na
  mesma chamada.
- README documenta o schema completo do `book.json`.
- Fixture `bras_cubas_excerpt.expected.vtt` não muda (o excerto tem ~95 palavras,
  abaixo do limiar de divisão); regressão do mock segue verde.

## ✅ Fase 2 — Suporte a PDF e EPUB

Implementação seguindo `docs/phase2-research.md` (memo aprovado).

- `extract/pdf.py`: `pypdf` (BSD, evita AGPL do PyMuPDF). Capítulos via
  outline; fallback para regex de heading; senão capítulo único.
  Detecção de PDF escaneado: chars/página < 100 → `UsageError` com
  instrução copy-pasteable. Flag `--auto-ocr` opt-in invoca `ocrmypdf`.
  Pós-processamento: dehifenização de fim de linha, normalização de
  espaços preservando parágrafos.
- `extract/epub.py`: `ebooklib` + `bs4`/`lxml` em modo tolerante.
  Capítulos na ordem do spine; título via cascata h1→h2→title→filename.
  `linear="no"` pulado por default com log explícito; flag
  `--include-auxiliary` traz de volta. Recuperação tolerante: cascata
  utf-8/cp1252/latin-1 no encoding, skip-com-warning de href inexistente,
  abort só se zero capítulos extraíveis. Limpeza de HTML remove
  `<script>`, `<style>`, tabelas, figuras, footnotes inline (`<sup>`,
  `epub:type="footnote"`).
- `chapter_split.py`: divide capítulos > 9000 palavras em partes de
  ~8000 palavras balanceadas em fronteira de parágrafo. Critério em
  palavras (não minutos), com tolerância 1.125× para evitar split
  desnecessário. Degradação para fronteira de sentença em parágrafo único
  gigante.
- `sanitize.py`: limpeza pré-TTS dos ~20 casos residuais que o tokenizer
  do XTTS não cobre (símbolos, emojis, controle, aspas/dashes
  tipográficos). Não toca em números — XTTS lê em pt-br corretamente.
- `chapter_range.py`: parser puro de `--chapters-only` aceitando lista,
  range e combinações (`1,3,5-7,10`), com 20 testes cobrindo
  sobreposição, range invertido, fora do range, lixo não-numérico.
- `pipeline.py`: integra tudo. Capítulos divididos geram
  `chapter_NN_part_MM.{mp3,vtt,txt}`; capítulos únicos seguem o naming
  da Fase 1 (`chapter_NN.{mp3,vtt,txt}`). `book.json` ganha `part`/
  `total_parts` apenas em entradas divididas (compatível com Fase 1.5).
- Testes: 129 ao todo (segment, package, extract/txt, extract/pdf 18,
  extract/epub 24, chapter_range 20, chapter_split 13, sanitize 25,
  config, mock regression). Regressão do mock no Brás Cubas continua
  byte-idêntica — sanitização e split não tocaram em capítulos curtos
  sem símbolos exóticos.
- Validação end-to-end com EPUB sintético: 3 capítulos (502, 12001, 502
  palavras), o longo dividido em 2 partes balanceadas, `book.json`
  correto, `--chapters-only 1,3` renumera sem gaps.

**Validação real (abr/2026, GPU RTX 4060 Ti):** "Memórias Póstumas de Brás
Cubas" (Project Gutenberg, EPUB) com limiar de split temporariamente
reduzido para ~1000 palavras forçando divisão real do capítulo. WhisperX
processou cada parte como sessão independente sem acumular deriva. O gap
de ~460 ms entre fim do último cue VTT (501.791 s) e fim do MP3 (502.251 s)
é trailing silence determinístico do XTTS-v2 — não dessincronização. Cada
parte exibe o mesmo gap, sem somar entre partes. Distinção documentada em
`backend/src/align.py`.

## ✅ Fase 3 — Seleção de voz (XTTS-v2 internos)

**Redesenho:** voice cloning a partir de gravação foi descartado como fluxo
principal. O XTTS-v2 já vem com dezenas de speakers pré-computados; é mais
valor com menos atrito do que pedir ao usuário para gravar/preparar uma
amostra. `--voice arquivo.wav` continua funcionando como caminho alternativo
(quem quer cloning de uma amostra arbitrária pode usar), mas o fluxo
recomendado passa a ser `--speaker NOME`.

- `src/voices.py`: `list_speakers()` carrega o XTTS-v2 lazy e retorna a lista
  alfabética dos speakers internos.
- Comando `python pipeline.py voices` imprime a lista em duas colunas + dica
  de uso. Aplica `apply_model_cache_env` antes para reaproveitar o cache de
  modelos. Falha graciosamente se `[tts]` não estiver instalado.
- Flag `--speaker NOME` em `build`. Validação em `_speaker_kwargs` levanta
  erro com lista dos disponíveis (até 20) + sugestão de rodar `voices` se o
  speaker pedido não existir.
- Conflito de flags: `--voice` + `--speaker` → `UsageError` explícito.
- Sem nenhuma das duas: aviso amarelo + fallback para o primeiro speaker
  interno (mantém comportamento da Fase 1 para smoke test).
- 9 testes em `test_voices.py` com stub de `TTS.api` injetado em
  `sys.modules` — validam ordenação alfabética, precedência voice > speaker
  > fallback, erro de speaker inexistente com lista truncada em listas
  longas, ausência de `coqui-tts` levantando ImportError.

**Cancelados** (em relação à proposta original): `record_voice.py` e
`prepare_reference.py` não serão escritos. Quem quiser cloning de gravação
própria pode produzir o WAV com qualquer ferramenta de áudio e passar via
`--voice`.

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
