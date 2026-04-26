"""
Parse extracted positional text into raw `(label, values, note)` rows.

This layer is purely mechanical: it detects statement headers, the period-column
header line, and reads each subsequent line as `<label> [<note>] <val1> <val2> ...`.
It does NOT know what `Receita líquida` means — that's the normalize layer's job.

Output is written to `data/interim/parsed/<doc_id>.json` as a list of raw rows.
"""
