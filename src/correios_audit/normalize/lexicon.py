"""
OCR-correction lexicon for the Correios brochure era + later scanned
quarterlies (e.g. 2023-Q2).

Two layers of repair:

1. `OCR_FIXES` — whole-string equality. Replaces a corrupted normalized
   label with its corrected form when the entire label matches a known
   damage pattern.

2. `OCR_SUBSTRING_FIXES` — bounded substring substitution. Rewrites a
   corrupted token in-place inside any larger label. Only safe when the
   corrupted form is unambiguous (i.e. has no plausible legitimate
   meaning on its own).

Both maps work on the *normalized* (lowercased, accent-stripped,
whitespace-collapsed) form, applied right after
`parse.common.normalize_label` and before the regex/fuzzy mapping pipeline.

Every entry was observed in real `data/interim/unmapped/*.csv` output.
"""

from __future__ import annotations

import re

# Whole-string matches (legacy entries; safer than substring because
# context-free).
OCR_FIXES: dict[str, str] = {
    # Capital-I → lower-l confusion (very common on serif scans).
    "lnadimplencia": "inadimplencia",
    "cobranca juridica/lnadimplencia": "cobranca juridica/inadimplencia",
    # 'rt' read as 'n'.
    "amonizacao": "amortizacao",
    "amonizacao acumulada": "amortizacao acumulada",
    "(-) amonizacao": "(-) amortizacao",
    # Trailing letters dropped or misread.
    "acumutaca": "acumulada",
    "(-) amonizacao acumutaca": "(-) amortizacao acumulada",
    # 'v' read as 'z'.
    "mozeis": "moveis",
    # Trailing 'q' artefacts from poorly-segmented characters.
    "qutros": "outros",
}

# Substring rewrites. Applied as whole-token replacements (word-boundary
# anchored) so they don't corrupt unrelated text.
#
# Rule: each key MUST be a damaged token unique enough that no legitimate
# Portuguese accounting term contains it. When in doubt, prefer extending
# a YAML pattern instead of adding an entry here.
OCR_SUBSTRING_FIXES: dict[str, str] = {
    # "Investimento" → "i ti t" — extreme letter-dropping observed on the
    # 2023-Q2 PDF (e.g. "propriedades para i ti t",
    # "ganho - valor justo - propriedades para i ti t"). The token "i ti t"
    # is gibberish in any other context.
    "i ti t": "investimento",
    # "apropriar" → "a i" — observed on the same PDF on
    # "adiantamentos de clientes e receitas a i". "a i" alone is too
    # ambiguous to substitute everywhere, so we only fix the multi-word
    # phrase below (whole-string entry).
}

# Multi-word phrase rewrites for cases where the corrupted form spans
# multiple tokens but only makes sense in one specific phrase.
OCR_PHRASE_FIXES: dict[str, str] = {
    # 2023-Q2: end of "a apropriar" got OCR'd as "a i" — only safe to
    # substitute when surrounded by the rest of the line.
    "receitas a i": "receitas a apropriar",
    # 2023-Q2: end of "prestados" got OCR'd as "t d" inside the CPV line.
    "e dos servicos t d": "e dos servicos prestados",
}


def _replace_bounded(text: str, old: str, new: str) -> str:
    """Replace `old` with `new` inside `text`, but only on word-boundary
    edges so the match can't bleed into adjacent words. Works for both
    single tokens ("i ti t") and multi-word phrases ("receitas a i") —
    the boundaries anchor the first/last character of `old`.
    """
    pattern = r"(?<!\w)" + re.escape(old) + r"(?!\w)"
    return re.sub(pattern, new, text)


def apply_ocr_fixes(normalized_label: str) -> str:
    """Return the corrected normalized label.

    Order of application:
      1. Whole-string match in `OCR_FIXES` (cheapest, most specific).
      2. Multi-word phrase substitutions from `OCR_PHRASE_FIXES`.
      3. Token substitutions from `OCR_SUBSTRING_FIXES`.

    Both 2 and 3 use word-boundary-anchored replacement so a fragment can't
    consume part of a longer word. Fixes compose: a label can match a
    phrase fix and then a token fix.
    """
    if normalized_label in OCR_FIXES:
        return OCR_FIXES[normalized_label]
    out = normalized_label
    for phrase, fix in OCR_PHRASE_FIXES.items():
        out = _replace_bounded(out, phrase, fix)
    for token, fix in OCR_SUBSTRING_FIXES.items():
        out = _replace_bounded(out, token, fix)
    return out
