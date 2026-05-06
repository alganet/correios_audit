# Manual overrides

When the parser cannot extract a figure (brochure layouts, OCR garbage, missing
date headers), drop a YAML file here with the value hand-typed from the source
PDF. `apply.py` ingests these on every run.

## Format

```yaml
source: "Demonstrações Financeiras de 2008, p.1 (BALANÇO PATRIMONIAL)"
url: "https://www.correios.com.br/.../demonstracoes-financeiras-de-2008"
sha256: "<sha256 of the source PDF>"
vintage_year: 2008
currency_unit: millions   # 'thousands' (default) | 'millions' | 'units'
page: 1
rows:
  - line_id: bp.ativo.total
    period_year: 2008
    period_kind: fy
    value: 6794.9
    source_page: 4
    source_quote: "...Total do Ativo passou de R$ 2.342.213.535,32 em 2000
                   para R$ 3.406.181.809,32 em 2001..."
```

Values are interpreted with the file's `currency_unit`. A value of `6794.9`
with `currency_unit: millions` is stored as 6,794,900,000 R$ (6.79 bi).

## Verifiable provenance

Every populated `value:` MUST carry:

- `source_quote:` — verbatim text from the PDF that contains the number, so a
  reader can confirm the figure in a few seconds without reopening the PDF.
- `source_page:` — page number in the original PDF (1-based).

The site's *Qualidade dos dados* view reads these fields and displays the
quote alongside each manual figure. If a row has `value: null`, the parser
ignores it — leave nulls for figures you haven't transcribed yet.

## Restatements allowlist

`restatements_allowed.yaml` lists `(line_id, period_year)` pairs whose drift
between vintages is intentional (e.g., a court ruling forced reclassification
of a Postalis liability between two annual reports). Each entry must include
a `reason:` field. The verify layer fails the build on any drift > 1% that
isn't allowlisted.

## When to use

- The source PDF is a designed brochure (2001–2009) with chaotic
  text-extraction order, so headline figures must be hand-keyed.
- A specific period column couldn't be bound (OCR misread date header).
- The audited opinion cites a value that the parser missed.

## When NOT to use

- The parser already extracted the value (don't duplicate; manual overrides
  win on tie at the latest vintage).
- The value is uncertain or you can't cite a specific PDF + page.

## Workflow

The repo includes scaffolding YAMLs (`2001.yaml` … `2009.yaml`, `2023-q2.yaml`)
with the headline line_ids pre-listed but `value: null` on rows where the
extraction couldn't be verified from the existing OCR. To populate them:

1. Open the source PDF (URL noted in each YAML).
2. Find the figure cited at the indicated page; copy the number.
3. Paste a verbatim ~one-sentence span into `source_quote`.
4. Type the value (in the unit declared at the top of the file).
5. Re-run `make verify` — the canonical now reflects the override.
