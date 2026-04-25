"""Sanitização de texto antes do TTS.

Decisão da Fase 2 (`docs/phase2-research.md` § 4): o tokenizer interno do
XTTS-v2 já lida com a maioria dos casos comuns em pt-br (acentos, números,
pontuação típica). Este módulo trata os ~20 casos residuais que sobram:

- **Unicode de controle e caracteres invisíveis** — removidos.
- **Símbolos não-falados pelo XTTS** — substituídos por equivalente em
  palavras quando faz sentido (`§` → "parágrafo", `→` → "leva a"), ou
  removidos.
- **Aspas e travessões tipográficos** — normalizados para variantes ASCII
  (vírgula simples, hífen) que o tokenizer cobre bem.
- **Emojis** — removidos. Não há sentido em ler emojis em audiobook.

**Não tocamos em números.** O tokenizer do XTTS lê "1999" como "mil
novecentos e noventa e nove" em pt-br corretamente. `num2words` não entra
como pré-processamento.
"""
from __future__ import annotations

import re
import unicodedata

# --- Substituições explícitas (símbolo → palavra falável) ---------------

# Ordem importa: regex multi-char ANTES de single-char. Alguns precisam de
# espaço ao redor para evitar grudar com a palavra vizinha.
_SYMBOL_SUBSTITUTIONS: list[tuple[str, str]] = [
    # Moeda
    ("R$", " reais "),
    ("US$", " dólares "),
    ("€", " euros "),
    ("£", " libras "),
    # Operadores e setas
    ("→", " leva a "),
    ("←", " vem de "),
    ("↔", " equivale a "),
    ("⇒", " implica "),
    ("⇔", " se e somente se "),
    ("≠", " diferente de "),
    ("≤", " menor ou igual a "),
    ("≥", " maior ou igual a "),
    ("±", " mais ou menos "),
    ("×", " vezes "),
    ("÷", " dividido por "),
    ("∞", " infinito "),
    # Tipográficos comuns
    ("§", " parágrafo "),
    ("©", " copyright "),
    ("®", " registrado "),
    ("™", " marca registrada "),
    ("°", " graus "),
    # Reticências unicode → três pontos ASCII (XTTS lida bem com "...").
    ("…", "..."),
]


# --- Normalização de aspas e travessões ---------------------------------

_QUOTE_NORMALIZATIONS = {
    # Aspas curvas → aspas retas
    "“": '"',  # "
    "”": '"',  # "
    "‘": "'",  # '
    "’": "'",  # '
    "‚": "'",  # ‚ (single low-9)
    "„": '"',  # „ (double low-9)
    "«": '"',  # «
    "»": '"',  # »
    # Travessões → hífen ASCII (XTTS pausa mais em hífen do que em em-dash).
    "—": "-",  # —
    "–": "-",  # –
    "−": "-",  # − (minus matemático)
    # Apóstrofos
    "ʼ": "'",  # ʼ
}


# --- Regexes de classes amplas -------------------------------------------

# Caracteres de controle Unicode (categoria Cc), exceto \n, \r, \t.
_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‏‪-‮⁠-⁯]"
)

# Emojis e pictogramas (cobre a maioria dos blocos comuns).
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f700-\U0001f77f"  # alchemical
    "\U0001f780-\U0001f7ff"  # geometric shapes ext
    "\U0001f800-\U0001f8ff"  # supplemental arrows
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess
    "\U0001fa70-\U0001faff"  # symbols & pictographs ext-a
    "\U00002700-\U000027bf"  # dingbats
    "\U00002600-\U000026ff"  # miscellaneous symbols
    "]+",
    flags=re.UNICODE,
)


# --- API pública ----------------------------------------------------------

def sanitize_for_tts(text: str) -> str:
    """Aplica todas as transformações na ordem certa.

    1. Normalização Unicode (NFC) para formas compostas estáveis.
    2. Substituições explícitas de símbolo → palavra.
    3. Normalização de aspas e travessões tipográficos.
    4. Remoção de emojis e pictogramas.
    5. Remoção de caracteres de controle.
    6. Colapsar espaços extras introduzidos.
    """
    text = unicodedata.normalize("NFC", text)

    for symbol, replacement in _SYMBOL_SUBSTITUTIONS:
        text = text.replace(symbol, replacement)

    for src, dst in _QUOTE_NORMALIZATIONS.items():
        text = text.replace(src, dst)

    text = _EMOJI_RE.sub("", text)
    text = _CONTROL_CHAR_RE.sub("", text)

    # Colapsa whitespace horizontal duplo (mas não \n\n de parágrafo).
    text = re.sub(r"[ \t]+", " ", text)
    # Tira espaços antes de pontuação que ficaram do replace.
    text = re.sub(r" +([,.;:!?])", r"\1", text)

    return text.strip()
