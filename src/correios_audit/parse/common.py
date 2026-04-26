"""
Shared parsing primitives:
- normalize_label: lowercase, strip accents, collapse whitespace
- parse_value: "1.234.567" / "(1.234.567)" / "-" → float | None
- detect_period_columns: find the X-positions of date headers
- looks_like_value: is this token a number or null marker?
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# A value token: 1.234.567, (1.234.567), 1.234.567,89, (1,5), or "-".
_NUM = re.compile(r"^\(?-?[\d.,]+\)?$")
_NUMERIC_CHAR = re.compile(r"\d")
# Strict Brazilian thousands-formatted value: e.g. 1, 12, 234, 1.234, 12.345.678,
# (1.234.567), 1.234,56. Distinguishes values from note refs like "21.1" or "11.3.2"
# (which have non-3-digit groups). Single integers up to 3 digits are allowed.
_VALUE_FORMAT = re.compile(
    r"""
    ^
    \(?                # optional opening paren for negatives
    -?                 # optional minus sign
    (?:
        \d{1,3}(?:\.\d{3})+   # thousands form: 1.234, 12.345.678
        |
        \d{1,3}               # short integer (used for sub-thousands values)
    )
    (?:,\d+)?          # optional decimal (comma)
    \)?                # optional closing paren
    $
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Word:
    x0: float
    x1: float
    text: str

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2


def words_from_line(line: dict) -> list[Word]:
    return [Word(w[0], w[1], w[2]) for w in line["words"]]


def normalize_label(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace, drop trailing punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(":.…·")
    return s


def looks_like_value(token: str) -> bool:
    t = token.strip()
    if t in ("-", "—", "–"):
        return True
    return bool(_VALUE_FORMAT.match(t))


def looks_like_note_ref(token: str) -> bool:
    """A note reference like 21, 21.1, 11.3.2, 18.2,18.3, possibly with a
    trailing comma when concatenated like '18.2,'."""
    t = token.strip().rstrip(",;")
    return bool(re.match(r"^\d+(?:\.\d+)*(?:[,;]\s*\d+(?:\.\d+)*)*$", t))


def parse_value(token: str) -> float | None:
    """Parse a Brazilian-formatted number. Returns None for '-' (null)."""
    t = token.strip()
    if t in ("-", "—", "–", ""):
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    # Brazilian: '.' is thousands separator, ',' is decimal.
    t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


# --- period-column detection ---------------------------------------------------

# Date forms that show up as headers: "31/12/2024", "31.12.2024", "01/01/2023", "2024".
_DATE_RE = re.compile(r"^(?:\d{1,2}[/.]\d{1,2}[/.]\d{4}|\d{4})$")
# Brazilian month abbreviations and full names used in older Correios reports
# like "31 dez 2014".
_MONTH_TOKENS = {
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez",
    "janeiro", "fevereiro", "marco", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    "de", "/",
}


@dataclass(frozen=True)
class PeriodColumn:
    label: str       # "31/12/2024"
    x_center: float
    period_year: int
    scope: str = "consolidado"   # "controladora" | "consolidado"


def _merge_textual_dates(words: list[Word]) -> list[Word]:
    """Merge sequences like ['31','dez','2014'] or ['31','de','dezembro','de','2014']
    into a single Word with combined text."""
    out: list[Word] = []
    i = 0
    while i < len(words):
        w = words[i]
        # Look for "<day> <month_token>+ <year>" where day and year are integers.
        if w.text.isdigit() and len(w.text) <= 2:
            j = i + 1
            month_seen = False
            while j < len(words) and words[j].text.lower().rstrip(".") in _MONTH_TOKENS:
                if words[j].text.lower().rstrip(".") not in {"de", "/"}:
                    month_seen = True
                j += 1
            if month_seen and j < len(words) and re.fullmatch(r"\d{4}", words[j].text):
                merged_text = " ".join(words[k].text for k in range(i, j + 1))
                out.append(Word(x0=w.x0, x1=words[j].x1, text=merged_text))
                i = j + 1
                continue
        out.append(w)
        i += 1
    return out


def detect_period_columns(line: dict) -> list[PeriodColumn]:
    """Find the period-header line: words that look like dates, sorted by x.

    Recognises three forms:
      "31/12/2024" / "31.12.2024"  — single token
      "2024"                        — bare year (older quarterlies)
      "31 dez 2014"                 — Portuguese spelled date, merged from
                                      consecutive tokens by `_merge_textual_dates`.
    """
    raw_words = words_from_line(line)
    words = _merge_textual_dates(raw_words)
    out: list[PeriodColumn] = []
    for w in words:
        if _DATE_RE.match(w.text):
            year = int(re.findall(r"(\d{4})", w.text)[-1])
            out.append(PeriodColumn(label=w.text, x_center=w.x_center, period_year=year))
            continue
        # Multi-token Portuguese spelled date — must contain whitespace, since
        # only `_merge_textual_dates` produces those (a CNPJ like
        # "34.028.316/0001-03" is a single token and won't be misclassified).
        if " " in w.text and re.fullmatch(r"\d{1,2}\s.+\s\d{4}", w.text):
            year = int(re.findall(r"(\d{4})", w.text)[-1])
            if year >= 1990:
                out.append(PeriodColumn(label=w.text, x_center=w.x_center,
                                        period_year=year))
    return out


def is_period_header(line: dict) -> bool:
    return len(detect_period_columns(line)) >= 1


_SCOPE_RE = re.compile(r"controladora|consolidado", re.I)


def _detect_scope_zones(lines: list[dict], header_idx: int,
                        look_back: int = 6) -> list[tuple[float, float, str]]:
    """Return [(x_min, x_max, scope), ...] from any line in the header zone
    (a few lines before/after `header_idx`) that lists 'Controladora' and/or
    'Consolidado' as column-group labels.

    A header line might look like:
        "Controladora    Consolidado"
    sitting above the date columns. We use the X positions of these scope
    words to define X-ranges. Each date column is then tagged with whichever
    range it falls into. If neither word is present, we return [], meaning
    every column gets the default scope ('consolidado').
    """
    start = max(0, header_idx - look_back)
    end = min(len(lines), header_idx + look_back)
    found: list[tuple[float, str]] = []  # (x_center, scope) sorted later
    for j in range(start, end):
        for w in words_from_line(lines[j]):
            m = _SCOPE_RE.match(w.text)
            if m:
                found.append((w.x_center, w.text.lower()))
    if not found:
        return []
    found.sort()
    # Build x-ranges from midpoints between adjacent scope labels.
    zones: list[tuple[float, float, str]] = []
    for i, (xc, scope) in enumerate(found):
        x_min = (found[i - 1][0] + xc) / 2 if i > 0 else float("-inf")
        x_max = (xc + found[i + 1][0]) / 2 if i + 1 < len(found) else float("inf")
        zones.append((x_min, x_max, scope))
    return zones


def detect_period_columns_in_zone(lines: list[dict], start_idx: int,
                                  zone_pt: float = 12.0) -> tuple[int, list[PeriodColumn]]:
    """Some PDFs split the date-header row across two adjacent y-buckets
    (Correios DVA does this). Starting at `start_idx`, gather all date
    columns within `zone_pt` vertical pixels. Returns (last_index_consumed,
    columns). De-dupes by (label, rounded x_center, scope) so 4-column
    Controladora+Consolidado layouts keep both copies of each date."""
    if start_idx >= len(lines):
        return start_idx - 1, []
    base_y = lines[start_idx]["y"]
    scope_zones = _detect_scope_zones(lines, start_idx)
    cols: list[PeriodColumn] = []
    last_idx = start_idx
    seen: set[tuple[str, int, str]] = set()
    for j in range(start_idx, len(lines)):
        if lines[j]["y"] - base_y > zone_pt:
            break
        for c in detect_period_columns(lines[j]):
            scope = "consolidado"
            if scope_zones:
                for x_min, x_max, s in scope_zones:
                    if x_min <= c.x_center < x_max:
                        scope = s
                        break
            tagged = PeriodColumn(label=c.label, x_center=c.x_center,
                                  period_year=c.period_year, scope=scope)
            key = (tagged.label, round(tagged.x_center / 4) * 4, tagged.scope)
            if key in seen:
                continue
            seen.add(key)
            cols.append(tagged)
            last_idx = j
    return last_idx, cols


def find_word(line: dict, target_text: str) -> Word | None:
    """Find a word matching exact text on a line (case-insensitive).

    Handles letter-spaced headers like "A T I V O" by checking adjacent
    1-character tokens.
    """
    target = target_text.lower()
    words = words_from_line(line)
    for w in words:
        if w.text.lower() == target:
            return w
    # Letter-spaced fallback: scan for sequences of 1-char tokens that join
    # into the target.
    for i in range(len(words)):
        joined = ""
        last_idx = i
        for j in range(i, len(words)):
            t = words[j].text
            if len(t) != 1 or not t.isalpha():
                break
            joined += t.lower()
            last_idx = j
            if joined == target:
                return Word(x0=words[i].x0, x1=words[last_idx].x1, text=target)
            if not target.startswith(joined):
                break
    return None


@dataclass
class RawRow:
    label: str
    note_ref: str | None
    values: dict[str, float | None]    # period_label → value
    page: int
    y: float
    side: str | None = None             # "ativo" / "passivo" / None
