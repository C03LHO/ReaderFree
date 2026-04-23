# Memo de pesquisa — Fase 2

**Escopo:** decisões técnicas da Fase 2 (extração de PDF e EPUB, segmentação de
capítulos, sanitização pré-TTS, flag `--chapters-only`). Este é um documento de
**decisão**, não de implementação — quando aprovado, vira o plano.

**Status:** v2, revisado após feedback. Mudanças principais desta revisão:

- OCR deixa de rodar por default; vira flag `--auto-ocr` opt-in (§ 1).
- Split de capítulo gigante passa de critério em minutos para critério em
  palavras, com quebra em fronteira de parágrafo (§ 3).
- Skip de `linear="no"` passa a logar explicitamente o item pulado (§ 2).
- Nova seção sobre EPUBs mal-formados (§ 2.4).
- Fase 1.5 detalhada com lista explícita de entregáveis (§ 6.1).

---

## 1. Extração de PDF

### Decisão proposta: **pypdf** como padrão, **pdfplumber** como fallback opcional

Manter `pypdf==5.1.0` (já no `pyproject.toml`) como extractor primário. Adicionar
`pdfplumber` nas deps do `[tts]` extra para um caminho opcional `--pdf-engine
pdfplumber`, útil quando o default falha em layout de duas colunas.

**Por que pypdf venceu.**

- No benchmark oficial do py-pdf (pypdfium2: 97 %, pypdf: 96 %, PyMuPDF: 96 %,
  pdfplumber: 75 %), `pypdf` fica empatado com PyMuPDF em qualidade agregada de
  extração de texto ([py-pdf/benchmarks](https://github.com/py-pdf/benchmarks)).
  Os 21 pontos de diferença para `pdfplumber` vêm do modo que este reordena por
  coordenadas — bom para formulários/tabelas, hostil para prosa corrida.
- Licença **BSD-3** (permissiva). PyMuPDF é **AGPL** com cláusula viral — mesmo
  em projeto pessoal, amarra a distribuição do instalador da Fase 7.5 se
  algum dia for público ([Artifex licensing](https://artifex.com/licensing);
  [Medium — "Stop Fighting with PDF"](https://medium.com/@alice.yang_10652/stop-fighting-with-pdf-the-7-python-libraries-you-should-know-eaf8a19c30e8)).
- Já está pinado na Fase 1. Zero atrito para adicionar.
- API de bookmarks estável: `reader.outline` retorna árvore recursiva de
  `Destination` com `title` e referência de página — o que a Fase 2 precisa para
  detectar capítulos.

**Alternativas consideradas.**

1. **PyMuPDF (fitz).** Velocidade 5–10× superior, melhor extração em layouts
   exóticos, API de outline idêntica à do pypdf. Descartada pela licença — nossa
   meta é um instalador Windows redistribuível (Fase 7.5) e AGPL complicaria
   qualquer divulgação, mesmo pessoal. Se a qualidade do pypdf se mostrar
   insuficiente em livros reais, reconsidero com a alternativa **pypdfium2**
   (MIT, binding do PDFium do Chromium, 97 % no benchmark).
2. **pdfplumber puro.** Melhor em preservar ordem em PDFs com coordenadas
   limpas, mas reordena agressivamente por `y`. Em livro narrativo com margem
   variável, quebra parágrafos na ordem errada. Vira fallback, não default.

**Acentuação.** Os três libs decodificam CMaps corretamente para texto Unicode
nativo. Mojibake em PDFs em pt-br acontece quando o PDF foi gerado com fontes
custom sem `/ToUnicode` — nenhum extractor Python resolve isso sem OCR. Abordagem:
detectar chars substituídos (`\ufffd` > 1 % do texto) e logar warning pedindo
OCR.

**Duas colunas.** pypdf extrai em ordem de stream (coluna inteira esquerda, depois
direita — comportamento correto para livros de ficção narrativa, que raramente
têm layout multi-coluna mesmo). Se usuário relatar livro técnico em colunas
bagunçando, a flag `--pdf-engine pdfplumber` fica disponível.

**Hifenização de fim de linha.** Nenhum dos três resolve automaticamente — PDF
não tem conceito de "linha lógica vs visual". Proposta: pós-processar no
`_normalize` do extract (regex `r"(\w+)-\n(\w+)"` → `r"\1\2"`), com whitelist de
palavras que terminam em `-` legítimo ("pós-graduação", "recém-nascido"). Lista
compilada de [MorphoBr](https://github.com/LR-POR/MorphoBr) ou simples regex que
só colapsa se o resultado formar uma palavra com sufixo gramatical coerente.
**Aceito imperfeição aqui** — "recomen-\ndação" errando vira "recomendação" e é
falado correto; hifenização legítima errando ("recém-nascido" → "recémnascido") o
TTS adivinha razoavelmente bem.

### Detecção de PDF escaneado

**Decisão proposta: heurístico chars/página + falha cedo com instrução; OCR
automático só atrás da flag opt-in `--auto-ocr`.**

`ocrmypdf` arrasta Tesseract, Ghostscript e qpdf — ~300 MB de deps nativas que
>95 % dos livros não vão precisar. Mesmo com `--skip-text` o processo rasteriza
cada página antes de decidir pular, o que custa minutos num livro grande sem
ganho algum. Default agressivo é errado aqui.

**Pipeline proposto:**

1. Extrair direto com pypdf.
2. Se `len(texto) / num_páginas >= 100`: seguir normal.
3. Se `< 100`: abortar com `UsageError` apontando solução exata —
   `"PDF parece escaneado (só X chars/página extraídos). Rode
   'ocrmypdf entrada.pdf saida.pdf' antes e reaplique o pipeline com saida.pdf.
   Ou passe --auto-ocr para invocar automaticamente se ocrmypdf estiver no PATH."`
4. Flag `--auto-ocr` opt-in: quando presente e `ocrmypdf` no PATH, rodar
   `ocrmypdf --skip-text --language por input.pdf temp.pdf` antes da extração.

**Por que o heurístico é "3 linhas que não são dívida técnica":**

- Livro típico: 1500–2500 chars/página. Limiar 100 é uma ordem de grandeza
  abaixo disso.
- Front matter (capa, rosto, dedicatória) pode ter <100, mas são 2–4 páginas em
  meio a 200+ — a média do livro inteiro não cai abaixo de 100 por causa delas.
- Falso positivo teórico: livro 100 % composto de imagens com legenda curta
  (álbum fotográfico). Não é nosso caso de uso.

**Alternativas consideradas (e rejeitadas).**

1. **Rodar `ocrmypdf --skip-text` incondicionalmente.** Proposta da v1 do memo.
   Elegante em teoria ("OCR decide sozinho"), mas custa deps pesadas + tempo de
   rasterização a cada livro. Rejeitada conforme feedback.
2. **Detectar via camada de fonte embutida (`/Font` objects no PDF).** Robustez
   idêntica ao heurístico chars/página, mas complexidade muito maior —
   pypdf expõe isso, mas a lógica vira 30 linhas vs 3. Não compensa.

**Fallback para livros sem bookmarks.** Pypdf expõe `reader.outline` (vazio em
PDFs sem outline). Quando vazio, tentar regex de heading sobre o texto completo:
`^(CAPÍTULO|Capítulo)\s+(\d+|[IVXLCDM]+)\b` e `^(\d+)\.\s+[A-ZÁÉÍÓÚÀÃÕÂÊÎÔÛÇ]`.
Se matches ≥ 2 e espaçados razoavelmente (>500 chars entre si), usar como
capítulos. Senão, **capítulo único**. Não tentar ser esperto demais — livro sem
TOC e sem heading óbvio ainda pode ser escutado como faixa única.

**Fallback para livros sem bookmarks.** Pypdf expõe `reader.outline` (vazio em
PDFs sem outline). Quando vazio, tentar regex de heading sobre o texto completo:
`^(CAPÍTULO|Capítulo)\s+(\d+|[IVXLCDM]+)\b` e `^(\d+)\.\s+[A-ZÁÉÍÓÚÀÃÕÂÊÎÔÛÇ]`.
Se matches ≥ 2 e espaçados razoavelmente (>500 chars entre si), usar como
capítulos. Senão, **capítulo único**. Não tentar ser esperto demais — livro sem
TOC e sem heading óbvio ainda pode ser escutado como faixa única.

---

## 2. Extração de EPUB

### Decisão proposta: `ebooklib==0.20` (oficial) + `beautifulsoup4` + `lxml`

Manter o que já está no `pyproject.toml`. `ebooklib` 0.20 foi lançado em
**2025-10-26** ([PyPI — EbookLib](https://pypi.org/project/EbookLib/)), então o
"sem manutenção" é mito desatualizado. Os forks `ebooklib-autoupdate` e
`EbookLib-re` sincronizam com o master mais agressivamente mas não adicionam
features — não valem o custo de sair do PyPI principal.

### Tratamento de `spine linear="no"`

**Decisão proposta: ignorar por default com log explícito; flag
`--include-auxiliary` para override.**

A spec EPUB 3 define `linear="no"` como **conteúdo auxiliar acessado fora da
sequência** — notas, apêndices, respostas
([IDPF — EPUB Publications 3.0.1](https://idpf.org/epub/301/spec/epub-publications.html);
[W3C EPUB 3.2](https://www.w3.org/publishing/epub32/epub-packages.html)). Apple
Books abre esses itens em janela sobreposta, não inline
([Apple Books Asset Guide — Nonlinear Content](https://help.apple.com/itc/booksassetguide/en.lproj/itc6120b3793.html)).

Para audiobook: incluir apêndices no meio da narração quebra a experiência.
Ignorar é o padrão correto. Flag `--include-auxiliary` permite quem quer fazer
dump completo (ex: livro técnico onde os apêndices importam).

**Adendo de log.** Ao ignorar, o CLI imprime uma linha por item pulado com o
título extraído (cascata de `<h1>` etc., mesma regra da próxima subseção):

```
[skipped] Apêndice A — Bibliografia (linear="no", use --include-auxiliary para incluir)
[skipped] Notas do tradutor (linear="no", use --include-auxiliary para incluir)
```

Usuário precisa saber o que não entrou no audiobook — silencioso demais vira
comportamento invisível.

**Alternativa considerada:** incluir tudo por default e deixar usuário pular com
`--chapters-only`. Rejeitada — quebra o default óbvio de "gerei o livro, plugo no
iPhone, funciona."

### Título de capítulo

**Decisão proposta: cascata `<h1>` → `<h2>` → `<title>` → nome do arquivo.**

Ordem testada com sucesso em readers como Calibre. Sem código aqui, mas a
lógica: pegar o primeiro `<h1>` do HTML. Se não existir, primeiro `<h2>`. Se não,
`<title>` da tag head. Último recurso: basename do arquivo HTML do spine, sem
extensão e com underscores → espaços.

**Edge case.** Alguns EPUBs têm `<h1>` só na capa (tipo "Livro Tal"). Se o mesmo
título aparecer em múltiplos capítulos, suffixar com índice: "Livro Tal (2)",
"Livro Tal (3)". Evita 40 capítulos com o mesmo nome na library.

### Sanitização de HTML antes do TTS

**Decisão proposta: whitelist mínima de tags de texto; descartar o resto.**

Tags que entram no texto: `<p>`, `<h1>`–`<h6>`, `<blockquote>`, `<em>`,
`<strong>`, `<i>`, `<b>`, `<li>` (com bullet em texto — "•" lido como pausa).

Tags que **descarto silenciosamente**: `<table>`, `<img>`, `<figure>`, `<svg>`,
`<audio>`, `<video>`, `<nav>` (TOC interno), `<aside>`, `<script>`, `<style>`.

Notas de rodapé **são o problema crítico.** Em EPUBs modernas, notas vivem em
`<a epub:type="noteref" href="#fn1">` com o texto da nota em `<aside
epub:type="footnote" id="fn1">`. Se inline, viram `1` ou `[1]` lidos em voz alta
no meio do parágrafo — ruído horroroso. **Decisão: remover `noteref` inteiramente
do corpo** (perde a referência em audio, aceito) e **não incluir `<aside>
epub:type=footnote` no texto do capítulo**. O leitor que quiser notas usa o PDF.

**Alternativa considerada:** ler a nota imediatamente após a sentença que a
refere, com prefixo "nota". Rejeitada por complexidade altíssima vs valor
questionável — experiência de audiobook comercial não faz isso.

### EPUB3 com mídia embutida

**Decisão proposta: avisar e ignorar.**

A spec EPUB 3 exige **fallback** textual para `<audio>`/`<video>` — conteúdo
estático lido quando o reader não suporta mídia
([W3C EPUB 3.2 — Content Documents](https://www.w3.org/publishing/epub32/epub-contentdocs.html)).
Extrair o fallback e tratar como texto normal. Se não houver fallback, logar
warning com o capítulo/posição e pular aquele nó.

Na prática, raríssimo em livros em pt-br. Não justifica solução elaborada.

### 2.4. EPUBs mal-formados

EPUB na prática é zona de guerra: encoding declarado errado no XML header,
tags HTML não fechadas, spine apontando pra `href` que não existe no
manifest, entidades HTML inválidas, caracteres de controle no meio do texto.

**Decisão proposta: recuperação tolerante, abortar só se nada for extraível.**

- **Parser HTML:** `BeautifulSoup` com `lxml` e `features="lxml"` (já nas
  deps). Lxml em modo HTML é intencionalmente tolerante — fecha tags
  abertas, ignora entidades inválidas, retorna DOM utilizável.
- **Encoding:** se o EPUB declara `encoding="utf-8"` mas o arquivo está em
  latin-1 (comum em EPUBs brasileiros antigos), tentar decode por tentativa
  na ordem `utf-8`, `cp1252`, `latin-1`. Não adicionar `chardet` como
  dependência nova — as três codificações cobrem 99 % dos casos reais. Se
  nenhuma funcionar, pular o arquivo com warning.
- **Spine com href inexistente:** logar warning (`[warn] spine aponta para
  'chapter_05.xhtml' mas o arquivo não existe no ZIP — capítulo pulado`) e
  continuar com os próximos.
- **Critério de aborto:** se `len(capítulos_recuperados) == 0`, abortar com
  `UsageError` listando os warnings acumulados para diagnóstico. Senão,
  seguir com o que foi recuperado e o resumo no fim da extração:
  `12 capítulos extraídos, 2 pulados (ver warnings acima)`.

**Por que não `chardet`.** Dependência extra que resolve um problema que
três tentativas de decode já cobrem. Se aparecer um livro real com encoding
exótico que essa ordem não pega, reconsidero — mas adiar a decisão.

**Alternativa considerada:** abortar no primeiro erro com mensagem clara e
exigir que o usuário conserte o EPUB antes. Rejeitada por dois motivos:
(a) usuário não tem ferramenta fácil pra consertar EPUB mal-formado; (b) em
90 % dos casos o livro é legível com 1–2 capítulos pulados, melhor entregar
isso do que zero.

---

## 3. Segmentação em capítulos no `book.json`

### Decisão proposta: split automático em **~8000 palavras**, quebrando em fronteira de parágrafo

O modelo atual (capítulos independentes, cada um com seu MP3/VTT) **escala bem
nos dois extremos que o usuário levantou**:

- **40 capítulos curtos (média 10 min):** 40 arquivos de ~7 MB cada. IndexedDB do
  iOS Safari aguenta tranquilo (quota ≥500 MB; com Safari 17+ e PWA instalada,
  até 60 % do disco
  ([WebKit — Updates to Storage Policy](https://webkit.org/blog/14403/updates-to-storage-policy/))).
  Seek dentro de faixa curta é instantâneo.
- **3 capítulos longos (80 000 palavras ≈ 10 h cada):** 3 arquivos de ~432 MB
  cada (96 kbps). **Aqui quebra.** Seek em MP3 CBR de 400 MB via `<audio>` no
  iOS é aceitável mas lento (2–5 s); em VBR fica pior.

**Critério de split: palavras, não minutos.** O que queremos limitar é tamanho
do arquivo MP3 (cache no iPhone + responsividade do seek do `<audio>`) e tamanho
do VTT (memória pra renderizar spans por palavra no frontend). Minutos variam
com velocidade do leitor (0.75×–2×), com voz clonada, com densidade do conteúdo
(diálogo rápido vs exposição densa) — é proxy instável. Palavras mapeiam direto
pra duração de áudio em velocidade normal e pra tamanho do VTT.

**Limiar: 8000 palavras por parte.** Em velocidade normal (~150 wpm) dá ≈45–55
min e ~43 MB de MP3 a 96 kbps. Em 1.5× fica ~30 min. Seek em arquivo desse
tamanho é instantâneo no Safari iOS.

**Quebra em fronteira de parágrafo, nunca no meio de sentença.** Procurar a
fronteira de parágrafo mais próxima do limiar (pode cair em 7600 ou 8400
palavras dependendo do texto); nunca dividir dentro de um parágrafo. Se o
parágrafo mais próximo ficar mais de 20 % longe do alvo, cair para quebra em
fronteira de sentença como degradação.

**Tolerância para não dividir desnecessariamente.** Se o capítulo tem ≤9000
palavras (8000 × 1.125), não dividir — o overhead de metadata extra + o jump
entre dois arquivos durante playback não compensa ganhar só 500–1000 palavras
de espaço. Capítulos de 9001+ dividem em 2 partes equilibradas, 17 001+ em 3,
etc., procurando sempre balanceamento com tolerância de 10 % por parte.

**Arquivos gerados e schema.** `chapter_05_part_01.mp3` /
`chapter_05_part_01.vtt`, `chapter_05_part_02.mp3` / `chapter_05_part_02.vtt`,
cada par independente. Entrada no `book.json` ganha `part` e `total_parts`,
mantendo `id` do capítulo igual para todas as partes. O formato de saída é o
mesmo que a v1 propunha — o que mudou foi só o racional do quando dividir.

**Alternativas consideradas.**

1. **Critério fixo em minutos (60 min), proposta da v1.** Rejeitada — proxy
   instável conforme acima.
2. **Um MP3 gigante com ID3 CHAP frames.** ID3 suporta capítulos internos
   ([id3.org — Chapter Frame Addendum](https://id3.org/id3v2-chapters-1.0)). Mas
   o `<audio>` do Safari iOS **não expõe** as chapter markers via Media Session
   API — só via reader custom. Teríamos que parsear ID3 no frontend. Complexidade
   alta para benefício marginal vs arquivos menores.
3. **Sempre capítulo único por arquivo, sem split.** Aceitar seek lento.
   Rejeitada — usuário específico levantou a preocupação e está certo.

### Revisão ao schema de `book.json`

Adicionar em cada entrada de capítulo:

- `part` (int, opcional, ausente quando capítulo não foi dividido)
- `total_parts` (int, opcional, ausente quando capítulo não foi dividido)

Capítulos não splitados ficam sem esses campos — retrocompatibilidade com livros
da Fase 1 preservada.

---

## 4. Caracteres que o XTTS-v2 não aguenta

### Descoberta importante: a maior parte da sanitização **já é feita pelo tokenizer**

Lendo [`tokenizer.py` do fork ativo idiap/coqui-ai-TTS](https://github.com/idiap/coqui-ai-TTS/blob/main/TTS/tts/layers/xtts/tokenizer.py):

- **Números em pt:** usa `num2words(amount, lang="pt")` internamente. "1999" vira
  "mil novecentos e noventa e nove". Datas e moedas funcionam.
- **Abreviações em pt:** `sr.→senhor`, `sra.→senhora`, `dr.→doutor`, `dra.→doutora`.
- **Símbolos em pt:** `&→" e "`, `@→" arroba "`, `%→" por cento "`, `£→" libra "`.

**O que resta para nós sanitizar (não coberto pelo tokenizer):**

| Categoria | Exemplo | Tratamento |
|---|---|---|
| Unicode de controle | `\u200b`, `\ufeff`, zero-width joiners | Remover silenciosamente |
| Seta e operadores | `→`, `↔`, `≈`, `∞`, `±`, `÷`, `×` | Substituir por equivalente falado em pt ou remover |
| Aspas/dashes tipográficos | `"` `"` `–` `—` `…` | Normalizar para ASCII equivalente |
| Símbolos monetários extras | `$`, `€`, `R$` | Substituir por "dólar(es)", "euro(s)", "reais" |
| Emoji | `🙂`, etc. | Remover |
| Matemáticos | `∑`, `∫`, `√`, `π` | Remover com warning (livro matemático não é nosso caso de uso) |

**Decisão proposta:** criar `backend/src/sanitize.py` com uma função
`sanitize_for_tts(text, language="pt")` que roda ANTES de `segment.split_sentences`.
Tabela de substituição pequena (~20 entradas) + regex para drop de control chars
e emojis. Teste unitário com cada linha da tabela.

**Não usar num2words diretamente no nosso código** — duplicaria o trabalho do
tokenizer. Deixa o XTTS lidar com números.

**Sobre a regra "R$ 1,50".** O tokenizer trata números e dois delimitadores
decimais (`,` e `.`), mas "R$" não está na lista de símbolos. Proposta: no nosso
sanitize, substituir `R\$\s*` por `"reais "` e deixar o número pro tokenizer.
Testar com fixture depois.

### Alternativa considerada

Pré-expandir todos os números nós mesmos com `num2words`. Rejeitada por
duplicação (o tokenizer já faz) e risco de divergência entre o que geramos e o
que o XTTS espera receber como tokens pré-normalizados.

---

## 5. Formato da flag `--chapters-only`

### Decisão proposta: **aceitar lista e ranges misturados**

Sintaxe: `--chapters-only 1,3,5-7,10` → `{1, 3, 5, 6, 7, 10}`.

**Por quê o formato "kitchen-sink":**

- **`--chapters-only 3`** (item único): caso mais comum em dev — regerar um
  capítulo só após fix. Contemplado.
- **`--chapters-only 1,3,5`** (lista): útil para iterar em capítulos de teste
  diversos.
- **`--chapters-only 1-3`** (range): útil para gerar os primeiros N capítulos
  (preview de livro longo antes de commitar CPU a gerar o resto).

A combinação (`1,3,5-7`) custa 5 linhas de parsing e cobre todos os 3 casos com
uma flag só. Recusar o range forçaria o usuário a escrever `1,2,3,4,5` para
pegar os primeiros 5 — atrito real.

**Alternativas consideradas.**

1. **Só item único (`--chapters-only 3`).** Minimalista demais. Iterar em um livro
   de 40 capítulos regenerando 5 em sequência vira pesadelo.
2. **Invocar a flag múltiplas vezes (`--chapters-only 1 --chapters-only 3`).**
   Click suporta, mas é verbose e não cobre ranges elegantemente. Rejeitada.

**Validação.** Se um capítulo pedido não existe (`--chapters-only 99` em livro de
40), erro `UsageError` listando os disponíveis, não fallback silencioso.

**Módulo isolado com testes.** O parsing fica em `backend/src/chapter_range.py`
(função pura `parse_chapter_range(spec: str, total: int) -> set[int]`), não
inline no `pipeline.py`. Testes unitários cobrem:

- Item único (`"3"` → `{3}`).
- Lista (`"1,3,5"` → `{1, 3, 5}`).
- Range (`"1-3"` → `{1, 2, 3}`).
- Combinação (`"1,3,5-7,10"` → `{1, 3, 5, 6, 7, 10}`).
- Sobreposição (`"1-3,2-4"` → `{1, 2, 3, 4}`, sem duplicatas).
- Range invertido (`"5-3"`) → `ValueError` com mensagem clara.
- Zero ou negativo (`"0"`, `"-1"`) → `ValueError`.
- Lixo não-numérico (`"abc"`, `"1-a"`) → `ValueError`.
- Fora do range do livro (`"99"` com total=40) → `ValueError` listando o
  disponível.
- Espaços toleráveis (`" 1 , 3 - 5 "` → `{1, 3, 4, 5}`).

---

## 6. Revisões sugeridas à Fase 1

Duas coisas que a pesquisa levantou e que valem a pena decidir agora.

### 6.1. Fase 1.5 — `book.json` ganha `part`/`total_parts`

**Proposta:** fazer **agora**, num único commit isolado, antes da Fase 2. O
custo é baixo e o benefício é evitar migração de schema quando EPUBs de
capítulo gigante chegarem.

**Entregáveis do commit da Fase 1.5:**

1. Em `backend/src/package.py`: aceitar `part` e `total_parts` opcionais por
   capítulo em `write_book_json`. Quando ambos forem `None` (caso default de
   capítulo não-dividido), os campos **não aparecem** no JSON — `null`
   explícito adiciona ruído; ausência é o sinal semântico correto.
2. Um teste novo em `backend/tests/test_package.py`: gera um `book.json` com
   capítulo dividido em 3 partes, valida que cada entrada tem `part` e
   `total_parts` corretos, e que um capítulo não-dividido na mesma chamada
   não recebe os campos. Teste existente de `book.json` continua passando
   sem mudança.
3. README atualizado com o schema completo do `book.json` — um bloco pequeno
   documentando `id`, `title`, `mp3_path`, `vtt_path`, `text_path`,
   `duration_seconds`, `word_count`, `part?`, `total_parts?`.

**Fixture de regressão do mock (`bras_cubas_excerpt.expected.vtt`):** não
muda. O VTT esperado é palavra-por-palavra do excerto (119 cues, 45.6 s); o
schema adicionado fica no `book.json`, não no VTT. O `chapter_01.mp3` e o
`chapter_01.vtt` da fixture de Brás Cubas são curtos (46 s, 95 palavras) —
não dividem. `test_mock_regression.py` continua passando byte-a-byte.

**Confirmação antes de commitar.** Rodar a suite inteira, rodar o pipeline
mock ponta-a-ponta na fixture, diffar o `book.json` gerado contra o da Fase
1 — a única diferença esperada é reformatação possível pela lib
`json.dump` (chaves novas ausentes não aparecem). Se aparecer diferença
inesperada, investigar antes de commitar.

**Trade-off:** gasta ~1h agora vs. aguentar refactor no meio da Fase 2. Voto
meu: fazer agora. É barato, desacopla a mudança de schema da mudança de
feature.

### 6.2. `sanitize.py` vs confiar 100 % no tokenizer do XTTS

Durante a pesquisa descobri que o tokenizer do XTTS já faz muito do trabalho
pesado de normalização (num2words, abreviações, símbolos principais). Isso
**reforça** a decisão atual de **não** pré-expandir números em
`segment.split_sentences`. Não há mudança a fazer em Fase 1 — é só confirmação
de que o caminho está certo.

**Armadilha latente a monitorar:** o `--mock` não invoca o tokenizer, então bugs
de sanitização só aparecem em geração real. Teste de regressão que roda em
hardware real (Fase 2 ou quando o PC com GPU estiver disponível) deve ter input
com `R$ 1,50`, `1999`, `Sr. Machado`, `→`, `—` para validar o pipeline real
contra o mock.

---

## Resumo das decisões para aprovação

1. **PDF:** `pypdf` default, `pdfplumber` como `--pdf-engine` opcional;
   detecção de PDF escaneado via heurístico chars/página < 100 com `UsageError`
   instrutivo; OCR automático **só atrás de `--auto-ocr` opt-in** (Tesseract e
   cia não entram no default). Fallback a capítulo único quando sem TOC.
2. **EPUB:** `ebooklib` oficial; `linear="no"` ignorado por default **com log
   explícito do item pulado** (flag `--include-auxiliary` para override); título
   via cascata h1→h2→title→filename; whitelist de tags textuais; notas inline
   removidas; mídia embutida avisa e pula; **recuperação tolerante para EPUBs
   mal-formados** (lxml HTML mode + cascata de encoding utf-8/cp1252/latin-1 +
   skip-com-warning de href inexistente; aborta só se zero capítulos
   recuperados).
3. **Split de capítulo gigante:** critério em **palavras, não minutos** — corta
   a cada ~8000 palavras em fronteira de parágrafo, com tolerância de 1.125×
   para não dividir desnecessariamente. Schema de `book.json` ganha
   `part`/`total_parts` (ausentes quando capítulo não é dividido).
4. **Sanitização pré-TTS:** módulo `sanitize.py` para unicode de controle,
   emojis, símbolos não-cobertos pelo tokenizer (setas, matemáticos, `R$`),
   aspas/dashes tipográficos. Números **ficam com o tokenizer do XTTS**.
5. **`--chapters-only`:** aceita lista + ranges misturados (`1,3,5-7,10`), com
   parsing isolado em `src/chapter_range.py` + testes unitários para
   sobreposições (`1-3,2-4` → `{1,2,3,4}`) e inválidos (`5-3`, `0`, `abc`).
6. **Fase 1.5 (revisão da Fase 1):** adicionar `part`/`total_parts` ao
   `book.json` agora, num commit isolado com teste e README atualizados,
   confirmando que a fixture de regressão do mock não muda.

---

## Fontes principais

- [py-pdf/benchmarks](https://github.com/py-pdf/benchmarks) — comparativo quantitativo
  de extractores PDF.
- [pypdf docs — comparisons](https://pypdf.readthedocs.io/en/stable/meta/comparisons.html)
- [PyMuPDF / Artifex licensing](https://artifex.com/licensing)
- [ocrmypdf — Introduction](https://ocrmypdf.readthedocs.io/en/latest/introduction.html)
  e [Advanced features](https://ocrmypdf.readthedocs.io/en/latest/advanced.html)
- [IDPF EPUB 3.0.1 — Publications](https://idpf.org/epub/301/spec/epub-publications.html)
- [W3C EPUB 3.2 — Packages](https://www.w3.org/publishing/epub32/epub-packages.html)
- [Apple Books Asset Guide — Nonlinear Content](https://help.apple.com/itc/booksassetguide/en.lproj/itc6120b3793.html)
- [ebooklib no PyPI (0.20, 2025-10-26)](https://pypi.org/project/EbookLib/)
- [idiap/coqui-ai-TTS — XTTS tokenizer.py](https://github.com/idiap/coqui-ai-TTS/blob/main/TTS/tts/layers/xtts/tokenizer.py)
- [num2words — savoirfairelinux](https://github.com/savoirfairelinux/num2words)
- [ID3v2 Chapter Frame Addendum](https://id3.org/id3v2-chapters-1.0)
- [WebKit — Updates to Storage Policy](https://webkit.org/blog/14403/updates-to-storage-policy/)
