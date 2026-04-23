# Memo de pesquisa — Fase 2

**Escopo:** decisões técnicas da Fase 2 (extração de PDF e EPUB, segmentação de
capítulos, sanitização pré-TTS, flag `--chapters-only`). Este é um documento de
**decisão**, não de implementação — quando aprovado, vira o plano.

**Status:** rascunho para revisão. Aguardando aprovação antes de escrever código.

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

**Decisão proposta: rodar `ocrmypdf --skip-text` incondicionalmente no input.**

O [`ocrmypdf`](https://ocrmypdf.readthedocs.io/en/latest/introduction.html)
detecta automaticamente se cada página já tem camada de texto e pula OCR nessas
páginas. `--skip-text` / `--mode skip` é idempotente em PDFs "born-digital" — roda
rápido e não mexe no arquivo. Em PDFs escaneados, cria a camada de texto.

Isso elimina a necessidade da heurística "chars/página < 100" proposta
originalmente. O heurístico é útil só para **avisar o usuário** se o input for
escaneado e ele não tiver `ocrmypdf` instalado.

**Pipeline proposto:**

1. Se `ocrmypdf` no PATH: rodar `ocrmypdf --skip-text --language por input.pdf
   temp.pdf` e extrair de `temp.pdf`.
2. Se `ocrmypdf` não está disponível: extrair direto com pypdf. Se
   `len(texto) / num_páginas < 100`, avisar "parece escaneado; instale ocrmypdf
   para OCR automático" e abortar (não gerar audiobook vazio).

Limiar 100 chars/página é conservador mas OK — uma página de livro típica tem
1500–2500 chars. Páginas de front matter (cover, rosto) são as únicas exceções
legítimas com pouco texto, e são poucas.

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

**Decisão proposta: ignorar por default, com flag `--include-auxiliary` opcional.**

A spec EPUB 3 define `linear="no"` como **conteúdo auxiliar acessado fora da
sequência** — notas, apêndices, respostas
([IDPF — EPUB Publications 3.0.1](https://idpf.org/epub/301/spec/epub-publications.html);
[W3C EPUB 3.2](https://www.w3.org/publishing/epub32/epub-packages.html)). Apple
Books abre esses itens em janela sobreposta, não inline
([Apple Books Asset Guide — Nonlinear Content](https://help.apple.com/itc/booksassetguide/en.lproj/itc6120b3793.html)).

Para audiobook: incluir apêndices no meio da narração quebra a experiência.
Ignorar é o padrão correto. Flag `--include-auxiliary` permite quem quer fazer
dump completo (ex: livro técnico onde os apêndices importam).

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

---

## 3. Segmentação em capítulos no `book.json`

### Decisão proposta: um MP3 por capítulo, com **split automático quando >1h**

O modelo atual (capítulos independentes, cada um com seu MP3/VTT) **escala bem
nos dois extremos que o usuário levantou**:

- **40 capítulos curtos (média 10 min):** 40 arquivos de ~7 MB cada. IndexedDB do
  iOS Safari aguenta tranquilo (quota ≥500 MB; com Safari 17+ e PWA instalada,
  até 60 % do disco
  ([WebKit — Updates to Storage Policy](https://webkit.org/blog/14403/updates-to-storage-policy/))).
  Seek dentro de faixa curta é instantâneo.
- **3 capítulos longos (80k palavras ≈ 10 h cada):** 3 arquivos de ~432 MB cada
  (96 kbps). **Aqui quebra.** Seek em MP3 CBR de 400 MB via `<audio>` no iOS é
  aceitável mas lento (2–5 s); em VBR fica pior.

**Proposta: split por capítulo se a duração estimada passar de 60 min.**
Arquivos gerados: `chapter_05_part_01.mp3`, `chapter_05_part_02.mp3`, cada um
com seu VTT independente. Entrada no `book.json` ganha `part: 1` e `total_parts:
3`, mantendo `id` do capítulo igual para todas as partes.

**Por quê 60 min:** mantém arquivos em ~43 MB, seek quase instantâneo, e ainda
dá uma divisão natural para o usuário ("parei na parte 2 do capítulo 5").

**Alternativas consideradas.**

1. **Um MP3 gigante com ID3 CHAP frames.** ID3 suporta capítulos internos
   ([id3.org — Chapter Frame Addendum](https://id3.org/id3v2-chapters-1.0)). Mas
   o `<audio>` do Safari iOS **não expõe** as chapter markers via Media Session
   API — só via reader custom. Teríamos que parsear ID3 no frontend. Complexidade
   alta para benefício marginal vs arquivos menores.
2. **Sempre capítulo único por arquivo, sem split.** Aceitar seek lento. Rejeitada
   — usuário específico levantou a preocupação e está certo.

### Revisão ao schema de `book.json`

Adicionar em cada entrada de capítulo:

- `part` (int, opcional, default 1)
- `total_parts` (int, opcional, default 1)

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

---

## 6. Revisões sugeridas à Fase 1

Duas coisas que a pesquisa levantou e que valem a pena decidir agora.

### 6.1. `book.json` — adicionar `part`/`total_parts`

**Proposta:** adicionar os campos **agora** (Fase 1.5, um commit pequeno) mesmo
que nenhum livro atual use split. Motivo: a fixture de regressão do mock
(`bras_cubas_excerpt.expected.vtt`) não é afetada, e quando a Fase 2 entrar com
EPUBs de capítulo gigante, o schema já está pronto — evita migração.

**Trade-off:** gasta tempo agora vs. aguentar a mudança depois. Voto meu: fazer
agora porque é barato (≤10 linhas de código + atualização de fixture de test_package).

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

1. **PDF:** `pypdf` default, `pdfplumber` como `--pdf-engine` opcional; OCR via
   `ocrmypdf --skip-text` incondicional quando disponível; fallback a
   capítulo único sem TOC.
2. **EPUB:** `ebooklib` oficial; `linear="no"` ignorado (flag
   `--include-auxiliary` para override); título via cascata h1→h2→title→filename;
   whitelist de tags textuais; notas inline removidas; mídia embutida avisa e
   pula.
3. **Split de capítulo gigante:** split em partes de 60 min. Schema de `book.json`
   ganha `part`/`total_parts`.
4. **Sanitização pré-TTS:** módulo `sanitize.py` para unicode de controle,
   emojis, símbolos não-cobertos pelo tokenizer (setas, matemáticos, `R$`),
   aspas/dashes tipográficos. Números **ficam com o tokenizer do XTTS**.
5. **`--chapters-only`:** aceita lista + ranges misturados (`1,3,5-7`).
6. **Revisão da Fase 1:** adicionar `part`/`total_parts` ao `book.json` agora
   (commit pequeno) para evitar migração depois.

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
