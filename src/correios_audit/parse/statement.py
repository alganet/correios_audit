"""
Generic single-table statement parser. Works for DRE, DRA, DFC, DVA, DMPL.

Strategy:
1. Find the line with date headers (e.g., "31/12/2024 31/12/2023") -> column X centers.
2. For each subsequent line: rightmost numeric tokens belong to value columns
   (assigned by nearest column X center). Tokens before the first numeric token
   form the label. A small NOTA token (like "21.1") may appear right before the
   first value.
3. Some PDFs split a row's label and values across two adjacent y-buckets
   (Correios DVA does this). When a line has only label text and the next line
   has only values within ~6pt, merge them.
"""

from __future__ import annotations

from dataclasses import dataclass

from correios_audit.parse.common import (
    PeriodColumn,
    RawRow,
    Word,
    detect_period_columns,
    detect_period_columns_in_zone,
    looks_like_note_ref,
    looks_like_value,
    parse_value,
    words_from_line,
)

_MERGE_GAP_PT = 14.0
# A word is "in" a column if its center is within this many pt of the column center.
COLUMN_TOLERANCE_PT = 22.0


@dataclass
class StatementParse:
    statement: str
    page: int
    columns: list[PeriodColumn]
    rows: list[RawRow]


def _word_in_value_zone(w: Word, columns: list[PeriodColumn]) -> bool:
    """Word is plausibly a value (close enough to some column center)."""
    return any(abs(c.x_center - w.x_center) <= COLUMN_TOLERANCE_PT for c in columns)


def _classify_words(
    words: list[Word], columns: list[PeriodColumn]
) -> tuple[list[Word], Word | None, list[Word]]:
    """Split words into (label_words, note_word, value_words) using column geometry.

    A word is a value only if (a) it looks numeric AND (b) it's within
    COLUMN_TOLERANCE_PT of some column center. This prevents tiny numeric tokens
    in the note column (e.g., "5") from being classified as the first value.
    """
    leftmost_col_x = min((c.x_center for c in columns), default=float("inf"))
    first_value_idx: int | None = None
    for i, w in enumerate(words):
        if looks_like_value(w.text) and _word_in_value_zone(w, columns):
            first_value_idx = i
            break
    if first_value_idx is None:
        # No values on this line at all. Treat everything as label/note.
        return words, None, []
    label = words[:first_value_idx]
    values = words[first_value_idx:]
    # Peel off trailing label tokens that are note refs (e.g. "21.1"),
    # short integers in the note region (e.g. "5", "9"), or Portuguese
    # conjunctions used to chain multiple note refs ("18.2, 18.3 e 19").
    note_tokens: list[Word] = []
    CONJUNCTIONS = {"e", "ou", "&"}
    NULL_MARKERS = {"-", "—", "–"}
    while label and label[-1].x_center < leftmost_col_x and (
        looks_like_note_ref(label[-1].text)
        or label[-1].text.lower() in CONJUNCTIONS
        or label[-1].text in NULL_MARKERS
    ):
        # Trailing null markers ("-", "—") between the label and the first
        # value column are the publisher's way of saying "no value for the
        # earliest period". Peel them so they don't pollute the label string
        # (e.g. "Empréstimos e Financiamentos 14.9 -" → "Empréstimos e
        # Financiamentos").
        note_tokens.insert(0, label[-1])
        label = label[:-1]
    note: Word | None = None
    if note_tokens:
        # Collapse consecutive note tokens into a single note ref.
        merged = " ".join(t.text for t in note_tokens)
        note = Word(x0=note_tokens[0].x0, x1=note_tokens[-1].x1, text=merged)
    return label, note, values


def _assign_values(
    value_words: list[Word], columns: list[PeriodColumn]
) -> dict[str, float | None]:
    """Assign each value-word to the nearest column. Dict key is
    "<period_label>|<scope>" so 4-column Controladora+Consolidado layouts
    preserve both pairs (otherwise both 31/12/2024 columns would collide).
    Single-scope layouts use the default scope so the suffix is always present.
    """
    out: dict[str, float | None] = {}
    for w in value_words:
        col = min(columns, key=lambda c: abs(c.x_center - w.x_center))
        if abs(col.x_center - w.x_center) > COLUMN_TOLERANCE_PT:
            continue
        key = f"{col.label}|{col.scope}"
        out[key] = parse_value(w.text)
    return out


def _try_merge_pair(line_a: dict, line_b: dict) -> dict | None:
    """If line_a has only label words and line_b has only value words,
    return a merged synthetic line. Otherwise None."""
    if abs(line_b["y"] - line_a["y"]) > _MERGE_GAP_PT:
        return None
    a_words = words_from_line(line_a)
    b_words = words_from_line(line_b)
    if not a_words or not b_words:
        return None
    a_has_value = any(looks_like_value(w.text) for w in a_words)
    b_has_value = any(looks_like_value(w.text) for w in b_words)
    a_only_label = not a_has_value
    b_only_value = b_has_value and not any(
        not looks_like_value(w.text) for w in b_words
    )
    if a_only_label and b_only_value:
        return {
            "y": line_a["y"],
            "words": line_a["words"] + line_b["words"],
        }
    return None


def _looks_like_strict_value(token: str) -> bool:
    """Stricter value heuristic for body-row column inference: real financial
    values are either thousands-formatted (digit groups separated by dots),
    parenthesised (negatives), or comma-decimal. Single integers like "18"
    match `looks_like_value` but they're typically NOTA refs, not real
    values, so we reject them at the inference step."""
    t = token.strip()
    if t in ("-", "—", "–"):
        return True
    if t.startswith("(") and t.endswith(")"):
        return True
    if "," in t:
        return True
    if "." in t and t.replace(".", "").replace("-", "").isdigit():
        return True  # 1.234, 12.345.678
    return False


def _infer_columns_from_body(
    lines: list[dict], start_idx: int, vintage_year: int | None
) -> tuple[int, list[PeriodColumn]] | None:
    """Fallback for OCR'd statements where the date header is absent or stray.

    Walk forward looking for the first body row whose trailing tokens are
    well-aligned numeric values. Cluster value X positions across the next ~8
    body rows; the most consistent cluster becomes the column set.

    Synthesises column labels using `vintage_year` and `vintage_year - 1`
    (and -2, -3 for 4-column Controladora+Consolidado layouts).

    Note: uses `_looks_like_strict_value` (not `looks_like_value`) to avoid
    treating single-digit NOTA references as values.
    """
    if vintage_year is None:
        return None
    candidate_xs: list[list[float]] = []
    for j in range(start_idx, min(start_idx + 30, len(lines))):
        words = words_from_line(lines[j])
        # Trailing values: split label/values heuristically by finding the
        # rightmost contiguous run of value-like tokens.
        value_xs: list[float] = []
        for w in reversed(words):
            if _looks_like_strict_value(w.text):
                value_xs.insert(0, w.x_center)
            else:
                break
        if len(value_xs) >= 2:
            candidate_xs.append(value_xs)
        if len(candidate_xs) >= 6:
            break
    if not candidate_xs:
        return None
    # Most common N (number of value columns)
    from collections import Counter
    n_counter = Counter(len(xs) for xs in candidate_xs)
    common_n, _ = n_counter.most_common(1)[0]
    cohorts = [xs for xs in candidate_xs if len(xs) == common_n]
    if not cohorts:
        return None
    # Average each column position across cohorts.
    avg_xs = [
        sum(xs[k] for xs in cohorts) / len(cohorts)
        for k in range(common_n)
    ]
    # Synthesise labels: rightmost = current, then prior, then ...
    # For 4-col Controladora+Consolidado, dates repeat (2017, 2016, 2017, 2016).
    if common_n == 4:
        years = [vintage_year, vintage_year - 1, vintage_year, vintage_year - 1]
    elif common_n == 2:
        years = [vintage_year, vintage_year - 1]
    elif common_n == 3:
        years = [vintage_year, vintage_year - 1, vintage_year - 2]
    else:
        years = [vintage_year - common_n + 1 + k for k in range(common_n)]
    cols = [
        PeriodColumn(label=f"31/12/{y}", x_center=x, period_year=y)
        for x, y in zip(avg_xs, years)
    ]
    return start_idx - 1, cols


def parse_simple_statement(
    page: dict,
    statement: str,
    *,
    min_columns: int = 2,
    vintage_year: int | None = None,
) -> StatementParse | None:
    """Parse a single-table statement page (DRE, DFC, DVA, etc.).

    `min_columns`: a body line like "Exercício 2014" has 1 detected date but
    isn't a real header. Real statement headers always show at least the
    current and prior period side-by-side (≥2 dates).

    `vintage_year`: used as fallback context when the date header is absent
    or unreadable. The body-row column-inference path uses it to label
    synthesised columns. If None, no fallback is attempted.
    """
    lines = page["lines"]
    # Find the first line whose date-column zone yields >= min_columns columns.
    header_start: int | None = None
    header_end: int | None = None
    columns: list = []
    for i, ln in enumerate(lines):
        if not detect_period_columns(ln):
            continue
        end, cols = detect_period_columns_in_zone(lines, i)
        if len(cols) >= min_columns:
            header_start = i
            header_end = end
            columns = cols
            break
    if header_start is None or not columns:
        # Body-row column inference was tried but produced unreliable results
        # for OCR'd quarterlies and BR-GAAP-era annuals (8-column layouts,
        # garbled headers). Without a clear date header we can't safely assign
        # values to periods, so we return None and accept the coverage gap.
        return None

    rows: list[RawRow] = []
    i = header_end + 1
    while i < len(lines):
        line = lines[i]
        # Try DVA-style two-line merge.
        merged = _try_merge_pair(line, lines[i + 1]) if i + 1 < len(lines) else None
        if merged is not None:
            i += 2
            words = words_from_line(merged)
            y = merged["y"]
        else:
            i += 1
            words = words_from_line(line)
            y = line["y"]

        # Skip page-number footers / "Em R$ milhares" / single-glyph noise.
        plain_text = " ".join(w.text for w in words).strip()
        if not plain_text:
            continue
        if len(words) == 1 and words[0].text.strip().isdigit():
            continue

        label_words, note_word, value_words = _classify_words(words, columns)
        values = _assign_values(value_words, columns)
        label = " ".join(w.text for w in label_words).strip()
        if not label and not values:
            continue
        if not label:
            label = "(continued)"
        rows.append(
            RawRow(
                label=label,
                note_ref=note_word.text if note_word else None,
                values=values,
                page=page["page"],
                y=y,
            )
        )
    return StatementParse(statement=statement, page=page["page"], columns=columns, rows=rows)
