"""Testes do sanitizador pré-TTS."""
from __future__ import annotations

from src.sanitize import sanitize_for_tts


# ============================================================================
# Substituições de símbolo → palavra
# ============================================================================

def test_substitui_moeda_real():
    assert "reais" in sanitize_for_tts("Custou R$ 50,00.")


def test_substitui_setas():
    out = sanitize_for_tts("A → B implica C")
    assert "leva a" in out
    assert "→" not in out


def test_substitui_operadores_matematicos():
    out = sanitize_for_tts("x ≠ y, então x ≤ z e a ≥ b")
    assert "diferente de" in out
    assert "menor ou igual a" in out
    assert "maior ou igual a" in out


def test_substitui_paragrafo_e_copyright():
    out = sanitize_for_tts("§ 12. © 2026 Foo Inc.")
    assert "parágrafo" in out
    assert "copyright" in out


def test_substitui_graus_e_porcentagem_de_temperatura():
    # ° vira "graus"; o tokenizer do XTTS lê números corretamente.
    out = sanitize_for_tts("Estava 30° de calor.")
    assert "graus" in out


def test_reticencias_unicode_viram_tres_pontos():
    out = sanitize_for_tts("Era assim… ele disse.")
    assert "…" not in out
    assert "..." in out


# ============================================================================
# Normalização de aspas e travessões
# ============================================================================

def test_aspas_curvas_viram_retas():
    out = sanitize_for_tts("Ele disse “olá” e “tchau”.")
    assert "“" not in out and "”" not in out
    assert '"olá"' in out and '"tchau"' in out


def test_aspas_simples_curvas_viram_retas():
    out = sanitize_for_tts("‘palavra’ entre aspas")
    assert "‘" not in out and "’" not in out
    assert "'palavra'" in out


def test_travessao_em_dash_vira_hifen():
    out = sanitize_for_tts("Frase — com travessão.")
    assert "—" not in out
    assert "-" in out


def test_travessao_en_dash_vira_hifen():
    out = sanitize_for_tts("Páginas 10–20.")
    assert "–" not in out
    assert "10-20" in out


# ============================================================================
# Emojis e pictogramas
# ============================================================================

def test_remove_emojis_basico():
    assert sanitize_for_tts("Olá 😀 mundo!") == "Olá mundo!"


def test_remove_emojis_de_blocos_diversos():
    # Cobre cada bloco do _EMOJI_RE.
    text = "a😀b🌍c🚀d♻️e"
    out = sanitize_for_tts(text)
    assert "😀" not in out and "🌍" not in out and "🚀" not in out
    assert "a" in out and "b" in out


def test_remove_emoji_pictograma():
    assert "✓" not in sanitize_for_tts("✓ feito")  # dingbat


# ============================================================================
# Caracteres de controle
# ============================================================================

def test_remove_chars_de_controle():
    text = "ola\x00mundo\x07!"
    out = sanitize_for_tts(text)
    assert "\x00" not in out
    assert "\x07" not in out
    assert "olamundo!" in out or "ola mundo!" in out


def test_remove_zero_width_chars():
    # zero-width space (U+200B), zero-width joiner (U+200D), BOM (U+FEFF).
    text = "ola​mundo‍fim"
    out = sanitize_for_tts(text)
    assert "​" not in out
    assert "‍" not in out


def test_preserva_quebras_de_linha_normais():
    text = "linha1\nlinha2\n\nparágrafo"
    out = sanitize_for_tts(text)
    assert "\n" in out
    # Parágrafos preservados (não vamos colapsar \n\n aqui).
    assert "\n\n" in out


def test_preserva_tab_porque_e_whitespace_normal():
    # \t é categoria Cc mas explicitamente excluído da nossa regex.
    out = sanitize_for_tts("a\tb")
    # Pode virar espaço único pelo colapso, mas não some inteiro.
    assert "a" in out and "b" in out


# ============================================================================
# Comportamento geral
# ============================================================================

def test_nao_toca_em_acentos_pt_br():
    text = "Memórias Póstumas de Brás Cubas, ação, coração, não."
    assert sanitize_for_tts(text) == text


def test_nao_toca_em_numeros():
    # Decisão da Fase 2: deixa o XTTS lidar com números.
    text = "O ano de 1999 e o número 1.234,56 ficam."
    out = sanitize_for_tts(text)
    assert "1999" in out
    assert "1.234,56" in out


def test_nao_toca_em_pontuacao_comum():
    text = "Frase com vírgula, ponto. E ponto-e-vírgula; e dois pontos: ok!"
    assert sanitize_for_tts(text) == text


def test_colapsa_espacos_apos_substituicoes():
    out = sanitize_for_tts("A   →   B")
    assert "  " not in out  # sem espaços duplos
    assert "leva a" in out


def test_remove_espaco_antes_de_pontuacao():
    out = sanitize_for_tts("frase , ponto . final !")
    assert "frase," in out
    assert "ponto." in out


def test_texto_vazio():
    assert sanitize_for_tts("") == ""


def test_texto_so_de_simbolos_vira_palavras():
    out = sanitize_for_tts("→ ← ↔")
    assert "→" not in out and "←" not in out and "↔" not in out
    assert "leva a" in out


def test_normalizacao_nfc_combinada():
    # 'á' como caractere combinado vs precomposto deve dar mesmo output.
    composed = "café"  # NFC
    decomposed = "café"  # NFD ('e' + combining acute)
    assert sanitize_for_tts(composed) == sanitize_for_tts(decomposed)
