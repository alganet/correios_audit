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
  - line_id: bp.passivo.total
    period_year: 2008
    period_kind: fy
    value: 6794.9
  - line_id: dre.receita_liquida
    period_year: 2008
    period_kind: fy
    value: 8493.4
```

Values are interpreted with the file's `currency_unit`. A value of `6794.9`
with `currency_unit: millions` is stored as 6,794,900,000 R$ (6.79 bi).

## When to use

- The source PDF is a designed brochure (2001–2009) with chaotic text-extraction order.
- A specific period column couldn't be bound (OCR misread date header).
- The audited opinion cites a value that the parser missed.

## When NOT to use

- The parser already extracted the value (don't duplicate; manual overrides
  win on tie at the latest vintage).
- The value is uncertain or you can't cite a specific PDF + page.
