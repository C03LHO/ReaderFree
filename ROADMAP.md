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

**Implementada; aguardando validação no iPhone** (depende da Fase 7 — deploy
ou Tailscale — para o servidor estar acessível pelo Safari iOS).

Implementação:

- `src/lib/types.ts`: `BookManifest`, `ChapterEntry`, `BookProgress`, `Prefs`
  espelhando o `book.json` do backend; `validateManifest` faz validação
  runtime na importação.
- `src/lib/storage.ts`: wrapper IndexedDB via `idb` com 4 stores:
  - `books` — manifest inteiro do `book.json`.
  - `assets` — Blobs MP3/VTT/TXT por `${bookId}/${filename}`, com índice
    `by-book` para deletar tudo de um livro com cursor.
  - `progress` — posição (chapterIndex + currentTime) por livro.
  - `prefs` — singleton com `playbackRate` global.
- `src/lib/import.ts`: `importBookFromZip(file, onProgress)` parsa via
  `jszip`, valida `book.json`, confirma que todos os arquivos referenciados
  existem, persiste cada asset com MIME type apropriado. Detecta prefixo
  de pasta raiz (caso `zip -r livro.zip livro/`).
- `src/components/Library.tsx` (client): grid de cartões com título/
  autor/duração/capítulos/progresso/badge mock; ordenação por
  `lastPlayedAt` desc; importação via `<input type="file">` hidden +
  feedback por fase (lendo, validando, extraindo, concluído); exclusão
  com `confirm()`.
- `src/components/Player.tsx` (client): carregamento de Blobs do
  IndexedDB com `URL.createObjectURL` + revoke no cleanup; hidratação
  inicial de progresso e prefs; controles play/pause, ±15s, velocidade
  (0.75/1/1.25/1.5/2x), capítulo anterior/próximo, barra de seek;
  avanço automático no `onEnded`; persistência de progresso com debounce
  de 1500ms.
- **Media Session API**: `metadata` (title/artist/album) +
  `setActionHandler` para play/pause/seekbackward/seekforward/
  previoustrack/nexttrack. Lock-screen do iPhone vai exibir os
  controles quando o PWA for instalado.
- React 19 + Next 16 lint rules
  (`react-hooks/set-state-in-effect`, `react-hooks/immutability`)
  forçaram patterns idiomáticos novos: refs trocadas por state
  (`pendingSeek`, `autoplayPending`), `useCallback` para funções
  referenciadas em deps de effects.

**Smoke test feito (sem iPhone real):**
- `pnpm build` passa limpo, gera 5 páginas estáticas + manifest.
- `pnpm exec tsc --noEmit` e `pnpm lint` zerados.
- Dev server: `GET /` 200 com markup "Biblioteca/Importar ZIP";
  `GET /reader/x` 200 (página de fallback "livro não encontrado");
  `manifest.webmanifest` válido.

**Pendente para fechar a Fase 4 com ✅:**
- Smoke test no Chrome desktop: importar um ZIP gerado pelo backend,
  abrir o reader, tocar áudio, conferir Media Session em controles de
  hardware (teclado de mídia).
- Validação no iPhone real (depois da Fase 7): instalar o PWA via
  Safari, importar ZIP via iCloud Files / AirDrop, verificar lock-screen
  com metadata + controles.

## ⬜ Fase 5 — Sincronização de texto (karaoke)

**Implementada; aguardando validação no iPhone** (mesma dependência da
Fase 4 — depende da Fase 7 ou Tailscale para teste no Safari iOS real).

Implementação:

- `src/lib/vtt.ts` (real, não mais stub): `parseVtt(raw)` retorna
  `WordCue[]` tolerando CRLF/CR/blocos NOTE/identificador opcional;
  `parseTimestamp(HH:MM:SS.mmm)` em segundos; `findActiveCueIndex(cues,
  time)` é busca binária O(log n) que cobre os 3 casos de borda
  (antes do primeiro / gap entre cues / depois do último — este último
  cobre o trailing silence ~500ms do XTTS documentado em
  `backend/src/align.py`).
- `src/components/TextViewer.tsx` (real): spans por palavra com
  `data-word-index`. Highlight CSS-driven via seletor
  `[data-active-index="N"] span[data-word-index="N"]` — o React só
  atualiza um atributo no parent, o(1) por mudança de palavra
  independente do tamanho do capítulo. Tap-to-seek via delegação,
  auto-scroll com `scrollIntoView({block:"center"})` que pausa 4s
  após scroll manual do usuário.
- `src/components/Player.tsx` (atualizado): carrega VTT junto com
  MP3/TXT, `requestAnimationFrame` enquanto tocando atualiza
  `currentTime` granular (~16ms), `activeWordIndex` é derivado via
  `useMemo` (não state próprio, evita lint
  `react-hooks/set-state-in-effect`). Três modos visuais por botões
  no header: karaoke (✦, default), plain (📖, texto rolante sem
  highlight), audio-only (🎧).
- `vitest.config.ts` + `pnpm test`: 20 testes em `src/lib/vtt.test.ts`
  cobrindo todos os casos de borda do parser e da busca binária. Tudo
  roda em 17ms (funções puras, environment node, sem jsdom).

Decisões:
- **Sem `react-window`**. Capítulos divididos pela Fase 2 ficam ≤9000
  palavras; 9000 spans em React 19 + Tailwind renderizam em ~30ms na
  primeira vez e ~1ms por mudança de palavra. Virtualização entra só
  quando virar problema concreto.
- **`activeWordIndex` derivado de `currentTime` via useMemo**, em vez
  de state separado atualizado por rAF. Garante consistência entre os
  caminhos rAF (tocando) e `onTimeUpdate` (pausado/seek).
- **Trailing silence preservado**: a busca binária mantém o highlight
  na última palavra durante os ~500ms de cauda do XTTS — não tenta
  esticar o cue.

**Pendente para fechar a Fase 5 com ✅:**
- Smoke test no Chrome desktop com um livro real (importar ZIP, abrir
  reader, conferir highlight sincronizado, tap em palavra pulando o
  áudio, alternar entre os 3 modos).
- Validação no iPhone real (depois da Fase 7).

## ⬜ Fase 6 — Refator arquitetural (servidor + library v2 + UI nova)

**Mudança de direção pedida pelo usuário** após a Fase 5: ZIP-import morre,
arquitetura vira "Natural Reader local" — servidor FastAPI persistente é
fonte da verdade, frontend (web/desktop/iPhone) é cliente puro. Decisões
detalhadas em `~/.claude/projects/.../memory/fase6_refator_arquitetural.md`.

### O que muda

- **Apaga** ZIP-import: `frontend/src/lib/import.ts`, botão "+ Importar ZIP",
  campos relacionados de `storage.ts`.
- **Library v1 plana** (`library/<livro>/`) **fica intocada como histórico**,
  mas o novo servidor não enxerga. Reprocessa quem quiser migrar.
- **`pipeline.py`** vira **biblioteca pura** (sem CLI Click). O servidor
  importa as funções; scripts batch também podem importar diretamente.
- **`book.json` schema v2**: + `cover_path`, `source_file`, `source_hash`,
  `status`, `progress`, `failure_reason`, `schema_version: 2`. Caminhos
  relativos.
- **Library v2** em `%LOCALAPPDATA%\ReaderFree\library\{book_id}\` com
  `meta.json` por livro + `_index.json` global (sem SQLite por enquanto;
  entra na Fase 10+ quando lista virar problema).
- **Idempotência por sha256** do arquivo de entrada — re-upload do mesmo
  PDF retorna `book_id` existente.

### Sub-fases

#### ✅ 6.1 — Backend FastAPI + worker + library v2

- Servidor `backend/server.py` em FastAPI escutando `127.0.0.1:8765`
  (sem auth, sem expor pra rede). Endpoints:
  - `POST /books` (multipart upload PDF/EPUB; `?mock=true` opcional)
  - `GET /books`, `GET /books/{id}`
  - `GET /books/{id}/cover`, `/source`
  - `GET /books/{id}/chapters/{n}/{audio,vtt,text,sentences}`
  - `DELETE /books/{id}`
  - `GET /books/{id}/progress` (polling 1s; SSE só se virar necessário)
  - `POST /books/{id}/promote` (sobe na fila)
  - `POST /queue/pause`, `POST /queue/resume`
- Worker em thread separada: fila `_index.json`, sequencial, flag de
  cancelamento entre chunks do XTTS, flag de pause global entre tarefas.
- `pipeline.py` refatorado em biblioteca pura (`build_book(...)`).
- Testes pytest+httpx para os endpoints + mock do worker para
  determinismo (sem GPU).
- Mantém comportamento de `--mock` como `mock=True` na função e como
  `?mock=true` no endpoint. Smoke test do worker no excerto Brás Cubas
  continua determinístico (mesma fixture VTT).

#### ✅ 6.2 — Capa + metadata refinada

- `extract/cover.py` cascata:
  1. PDF: primeira imagem da primeira página (>60% da área) via pypdf.
  2. EPUB: `properties="cover-image"` (EPUB 3) ou `<meta name="cover">`
     (EPUB 2) via ebooklib.
  3. Fallback: PIL gera 600×900 com cor sólida derivada do hash do título
     + título e autor centralizados em fonte system-default.
- `extract/metadata.py` lê título/autor:
  - PDF: `reader.metadata` → fallback nome do arquivo limpo.
  - EPUB: `<dc:title>`, `<dc:creator>`.
- Pillow entra como dep do backend.
- Testes com fixtures de PDF e EPUB (com e sem capa nativa).

#### ⬜ 6.3 — Frontend refatorado

- **Apaga** `lib/import.ts`, `lib/storage.ts` (storage vira só cache de
  preferências/progresso por livro), tela inicial de importar ZIP.
- **Layout novo**: sidebar fina à esquerda com 3 ícones (Adicionar, 📚,
  ⚙). Área principal contextual.
- **Tela Adicionar**: dropzone PDF/EPUB. Cards de livros em fila com
  barra de progresso atualizada via polling 1s.
- **Tela Biblioteca**: grid de cards com capa 300×450, título, autor,
  % lido. Hover mostra "Editar metadados" e "Apagar".
- **Tela Player**: layout estilo Natural Reader. Modo padrão é
  **destaque por frase** (consume `chapter_NN.sentences.json` do
  servidor) com fundo âmbar suave. Tap numa frase pula o áudio.
  Mantém modo "palavra" e "audio-only" como avançados (botões no
  header). Player carrega assets via fetch da API (não mais IndexedDB).
- **Tela Configurações**: idioma da UI, voz padrão (lista vinda de
  `GET /voices`), velocidade padrão, caminho da biblioteca, URL do
  servidor (pra iPhone). Token Bearer + QR code de pareamento entram
  aqui.
- **Tradução completa pt-BR** — sem string em inglês na UI final.

#### ⬜ 6.4 — Desktop PyWebview

- `desktop/main.py` lança uvicorn em thread + abre janela PyWebview
  apontando para `http://127.0.0.1:8765`.
- Fechamento da janela mata o servidor limpo.
- `desktop/icon.ico`, `desktop/requirements.txt` (fastapi, uvicorn,
  pywebview, pillow + tudo o que o backend precisa).
- Documentação em `README` de como rodar (`python desktop/main.py`).

## ⬜ Fase 7 — Offline / service worker

**Renumeada** (era Fase 6 antes da refatoração de Fase 6).

- **Serwist** (`@serwist/next` + `serwist`) com `src/app/sw.ts`.
- Cache strategies adaptadas à nova API:
  - App (HTML/CSS/JS Next): CacheFirst.
  - `GET /books/{id}/chapters/.../audio|vtt|text|sentences`: CacheFirst
    com limite por livro.
  - `GET /books/{id}/cover`: CacheFirst.
  - `GET /books`, `GET /books/{id}`, `GET /books/{id}/progress`:
    NetworkFirst (sempre tenta servidor, fallback cache).
- Indicador "offline" no header.
- Tela "downloads" (sub-tela de Configurações): tamanho em cache,
  limpar por livro.
- Testar em modo avião com PWA instalada na home screen do iPhone.

## ⬜ Fase 8 — Deploy e acesso do iPhone

**Renumeada** (era Fase 7).

Foco: rodar servidor no PC e acessar do iPhone via Tailscale.

- **Caminho principal**: usuário liga "expor pra Tailscale" nas
  Configurações do app desktop. Servidor passa a escutar `0.0.0.0:8765`
  e gera token Bearer.
- App desktop mostra QR code com `https://<tailscale-name>:8765?token=...`
  pra escanear no iPhone Safari → adiciona aos PWAs instalados.
- iPhone PWA: tela de "primeira conexão" pede URL+token (ou QR scan
  via `<input capture>`).
- **Caminho alternativo (LAN sem Tailscale)**: descobre IP via
  `ipconfig`, mostra URL `http://<IP>:8765`. Funciona em casa, não fora.
- **Não vamos** mais hospedar no Cloudflare Pages — frontend é servido
  pelo servidor local. Internet aberta entra só se virar requisito real.

## ⬜ Fase 9 — Empacotamento desktop (Windows)

**Renumeada** (era Fase 7.5). Muito mais simples agora porque a Fase 6.4
já entregou um desktop funcional — só falta empacotar.

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

## ⬜ Fase 10 — Polimento (backlog)

**Renumeada** (era Fase 8). Só se 0–9 estiverem sólidas.

- Bookmarks.
- Highlight manual + export markdown.
- Multi-idioma no mesmo livro (autodetect por capítulo).
- Dicionário de pronúncia custom (aplicado antes do TTS).
- Regenerar frase isolada sem reprocessar livro.
- Multi-speaker (narrador + diálogos).
