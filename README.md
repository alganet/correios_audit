# Auditoria financeira dos Correios

Auditoria de longa duração, no nível de cada conta contábil, da **Empresa
Brasileira de Correios e Telégrafos (ECT)**, reconstruída a partir das
demonstrações financeiras públicas em PDF — **2001 a 2024**. O resultado é um
site HTML estático, navegável e portátil, gerado de forma reproduzível.

Fonte:
<https://www.correios.com.br/acesso-a-informacao/institucional/publicacoes/demonstracoes-financeiras>
(106 PDFs: demonstrações anuais, ITRs trimestrais dos exercícios mais
recentes, relatórios dos auditores independentes e pareceres do Conselho
Fiscal).

## Por que?

Não há, hoje, uma visão pública consolidada da trajetória financeira dos
Correios ao longo de mais de duas décadas. As informações estão fragmentadas
em PDFs heterogêneos, com plano de contas em mutação durante a transição
**BR-GAAP → IFRS (~2008–2010)** e diversas reapresentações (restatements) ao
longo do tempo. Este projeto reconstrói uma única **base de dados canônica** a
partir desses PDFs e a apresenta como site navegável.

Sem assistência de LLMs no caminho de extração: tudo é determinístico,
reproduzível e auditável.

## Visão geral do pipeline

```
fetch  →  extract  →  parse  →  normalize  →  verify  →  site
PDFs      texto/      linhas    parquet      build-     HTML
          OCR         brutas    canônico     gating
```

| Etapa       | Ferramentas                                              | Saída                                                                    |
|-------------|----------------------------------------------------------|--------------------------------------------------------------------------|
| `fetch`     | `httpx` + `tenacity`                                     | `data/raw/pdfs/<sha256>.pdf` + `manifest.jsonl`                          |
| `extract`   | `pymupdf` (texto) + `paddleocr`/`opencv` (OCR)           | `data/interim/text/<doc_id>.json` (palavras + confiança por página)      |
| `parse`     | parsers próprios (BP, DRE, DRA, DFC, DVA)                | `data/interim/parsed/<doc_id>.json`                                      |
| `normalize` | mapeamentos YAML + fuzzy/OCR fallback (rapidfuzz)        | `data/processed/canonical.parquet`                                       |
| `verify`    | cross-foots, sinal, DFC↔BP, variação entre reapresentações, materialidade | código de saída (falha a build em caso de erro)            |
| `quality`   | rollup por safra/doc                                     | `data/processed/quality.json`                                            |
| `site`      | templates Jinja2 + Plotly + view de qualidade            | `data/site/` (inclui `qualidade/`)                                       |

A escolha entre extração de texto e OCR é **automática**, baseada na densidade
textual das primeiras páginas de cada PDF. Brochuras escaneadas (tipicamente
2001–2009) passam por OCR via PaddleOCR (modelo `latin`, com deskew/binarize
em OpenCV); documentos nativos digitais (2011+) usam extração direta via
pymupdf. Cada palavra extraída tem um valor de confiança associado (1,0 para
texto nativo; score do reconhecedor para OCR) que é propagado até a página de
qualidade.

## Instruções

```bash
uv sync                  # cria .venv com as deps Python (3.12)
make fetch               # baixa os 106 PDFs em data/raw/pdfs/
make extract             # roteamento texto + OCR → data/interim/text/
make normalize           # plano de contas canônico → data/processed/canonical.parquet
make verify              # cross-foots + materialidade + golden fixtures
make site                # gera o site estático em data/site/
python -m http.server -d data/site 8000
# abrir http://localhost:8000
```

Na primeira execução de `make extract`, o PaddleOCR baixa cerca de **250 MB
de pesos do modelo** (cacheados em `~/.paddleocr/`); execuções subsequentes
são totalmente locais. Não há mais dependência de `tesseract`/`ocrmypdf` no
caminho padrão — o motor antigo permanece disponível através de
`make extract --ocr-engine=tesseract` para quem quiser comparar resultados.

Sistema (apenas para o motor antigo, opcional):

```bash
sudo apt install tesseract-ocr tesseract-ocr-por ghostscript unpaper
```

## Estrutura do projeto

```
src/correios_audit/
  catalog.py             # registro estático de docs: 106 PDFs ao longo de 25 anos
  fetch.py               # downloader ciente de redirecionamentos do Plone
  extract/
    router.py            # roteamento por densidade de texto (texto vs OCR)
    text.py              # extrator posicional via pymupdf
    ocr.py               # interface sobre ocrmypdf
  parse/
    bp.py                # Balanço Patrimonial (lado a lado e coluna única)
    statement.py         # parser genérico (DRE/DRA/DFC/DVA)
    common.py            # detecção de colunas, parsing de valores BR, datas em pt-BR
  normalize/
    taxonomy.py          # plano de contas canônico (dataclasses imutáveis)
    mappings/            # um YAML por demonstração (bp, dre, dra, dfc, dva)
    apply.py             # bruto → canônico, com inferência de lado e period_kind
  verify/
    checks.py            # cross-foot, tie-out de auditoria, materialidade
    golden/              # figuras conferidas à mão por exercício (CSV)
  site/
    build.py             # Jinja2 → HTML estático
    templates/, static/
data/
  raw/pdfs/              # gitignored
  interim/               # gitignored
  processed/             # canonical.parquet (versionado)
  manual_overrides/      # YAML para sobrescritas manuais (anos OCR-incompletos)
  site/                  # saída do build, gitignored
```

`src/`-layout para evitar shadowing de imports a partir de `tests/`. **Parquet**
para o canônico (tipado, rápido). **JSONL** para o manifest bruto (append-only,
fácil de auditar e diferenciar).

## Esquema canônico

Cada linha do parquet canônico tem o formato:

```
doc_id | vintage_year | statement | side | line_id |
period_year | period_kind | scope | value | page | label_raw | note_ref
```

- **`vintage_year`** — ano em que o relatório foi publicado.
- **`period_year` + `period_kind`** — ano e tipo de período sendo reportado;
  `period_kind ∈ {fy, q1, q2, q3}`.
- **`line_id`** — identificador estável na taxonomia
  (ex.: `dre.receita_liquida`,
  `bp.passivo.nao_circulante.beneficios_pos_emprego`).
- **`scope` ∈ {controladora, consolidado}** — qual visão a linha representa.
- **`value`** — em R$ nominais (já reescalado conforme a unidade publicada
  naquele ano; ver "Tratamento de unidade monetária" abaixo).

**Reapresentações são preservadas**: a chave primária inclui `vintage_year`,
então o relatório de 2018 reapresentando 2017 coexiste com o relatório
original de 2017. Visões padrão usam o vintage mais recente; a página de
restatements destaca linhas onde `|último − original| / |original| > 1%`.

## Taxonomia canônica

A taxonomia está em [`taxonomy.py`](src/correios_audit/normalize/taxonomy.py)
como dataclasses imutáveis. Cada linha tem `line_id`, `parent`,
`sign_convention` (sinal esperado: `+`, `-`, `any`), `valid_from`/`valid_to`
(janela de vigência) e categoria (BP, DRE, DRA, DFC, DVA).

Atualmente: **190 line\_ids** ativos. A hierarquia é codificada no nome
pontuado:

```
bp.ativo
bp.ativo.circulante
bp.ativo.circulante.caixa_equivalentes
bp.ativo.circulante.caixa_equivalentes.caixa
bp.ativo.circulante.caixa_equivalentes.bancos
...
```

A passagem **BR-GAAP → IFRS** (2008–2010) é tratada com `valid_from` /
`valid_to` por linha. Linhas como `bp.ativo.disponivel`, `bp.ativo.permanente`,
`dre.lucro_operacional_liquido`, `dre.juros_capital_proprio` e
`dre.reversao_jcp` existem só no período pré-IFRS (`valid_to: 2010`); linhas
como `dra.*` (Resultado Abrangente) e `bp.*.passivo_direito_uso` (IFRS 16) só
no pós-IFRS (`valid_from: 2010` ou `2019`).

## Mapeamentos (label → line\_id)

A normalização usa **regex em YAML**, em
[`normalize/mappings/`](src/correios_audit/normalize/mappings/) — um arquivo
por demonstração. Cada regra tem:

```yaml
- pattern: '^caixa e equivalentes? de caixa$'
  side: ativo                              # opcional, só BP
  line_id: bp.ativo.circulante.caixa_equivalentes
  where: 'parent_section == "circulante"'  # opcional, contexto
```

Os padrões são aplicados sobre a forma **normalizada** do rótulo (minúsculas,
sem acentos, espaços colapsados). A primeira regra correspondente prevalece.

**Rótulos não mapeados não são silenciosamente descartados**: vão para
`data/interim/unmapped/<doc_id>.csv`. Linhas não-mapeadas que excedem **0,5%
da receita líquida** fazem o build falhar — é o que mantém a taxonomia honesta.

## Tratamento de unidade monetária

Os relatórios usam unidades diferentes ao longo dos anos. As escalas
detectadas por inspeção das fontes:

- **2001–2007**: R$ brutos (`Valores em R$`)
- **2008–2009**: milhões de R$ (cabeçalho diz `Em milhares` mas os valores
  estão claramente em milhões — Total do Ativo `6.794,9` ≈ R$ 6,79 bi)
- **2010**: R$ brutos novamente (`Valores em R$`)
- **2011 em diante**: milhares de R$ (`Em milhares de R$`)

As escalas estão hard-coded em
[`normalize/apply.py`](src/correios_audit/normalize/apply.py) com base na
unidade declarada em cada PDF. Se um documento futuro adotar outra unidade,
sobrescreva via `data/manual_overrides/`.

## Controladora vs Consolidado

A maioria dos relatórios anuais brasileiros traz BP e DRE em duas visões
lado a lado: **Controladora** (somente a empresa-mãe) e **Consolidado**
(grupo, incluindo subsidiárias como CorreiosPar). O esquema canônico carrega
a coluna `scope` (`controladora` ou `consolidado`).

Por padrão, o site e as queries retornam `consolidado` (a visão externa
padrão) e caem para `controladora` quando a consolidada não está disponível
naquele período.

## Verificação (`make verify`)

Cinco camadas, todas bloqueando a build em caso de falha (sem aceitação
condicional por safra):

1. **Cross-foots** — por período:
   - BP: `Total do Ativo == Total do Passivo + Patrimônio Líquido`.
   - DRE: `Receita Líquida + CPV == Lucro Bruto`.
   - DRE: `Resultado antes do IR + Tributos + PLR + reversão de JCP ==
     Resultado Líquido`. As pernas pré-IFRS (PLR e reversão de JCP) são
     incluídas automaticamente quando os valores existem para aquela
     vintage.
   - **DFC ↔ BP cash recon**: `dfc.caixa_fim == bp.ativo.circulante.caixa_equivalentes`,
     tolerância 0,5% do caixa.
2. **Convenção de sinal** — toda linha cuja taxonomia declara `sign='+'` ou
   `sign='-'` deve casar. CPV positivo no canônico = falha. Linhas
   `sign='any'` são ignoradas.
3. **Variação entre reapresentações** — para `(line_id, period_year)`
   reportado em ≥2 safras, falha quando `|último − primeiro| / |primeiro| > 1%`.
   Reapresentações legítimas devem ser registradas em
   `data/manual_overrides/restatements_allowed.yaml` com o campo `reason:`
   justificando o caso.
4. **Gate de materialidade** — qualquer linha não-mapeada acima de **0,5% da
   receita líquida** quebra o build, sem exceção. Brochuras escaneadas
   pré-2010 e o ITR 2023-Q2 devem cobrir suas figuras-headline via
   `data/manual_overrides/<year>.yaml`.
5. **Golden fixtures** — `verify/golden/<year>.csv` contém figuras conferidas
   à mão por vintage. Hoje há fixtures para **2014, 2019, 2021 e 2024**
   (cobrindo a transição BR-GAAP → IFRS, o pós-IFRS estável, o pico
   COVID-19/e-commerce e o exercício mais recente). A tolerância de cada
   linha é 0,5% do valor esperado, com mínimo de R$ 1.000.

## Qualidade dos dados (`make quality` + view no site)

`make quality` produz `data/processed/quality.json` com, por documento:
método de extração, confiança OCR média, contagens de linhas
canônicas/fuzzy/não-mapeadas, cross-foots BP/DRE em R$, e violações de
sinal. O site renderiza isso em `qualidade/index.html` (resumo por safra) e
`qualidade/<vintage>.html` (detalhe por documento, com citações verbatim
para cada figura de override manual).

## Limitações conhecidas

- **DMPL** (Demonstração das Mutações do Patrimônio Líquido): movimentação
  multi-coluna do patrimônio; adiada — a estrutura publicada é
  eventos × componentes do PL e exige um parser próprio.
- **Tie-out do parecer dos auditores**: o verificador suporta isso
  conceitualmente, mas ainda não há regras que extraiam valores cabeçalho do
  texto narrativo do parecer.
- **Aritmética da DRE pré-2008**: rótulos BR-GAAP estão mapeados (Receita
  operacional bruta, Lucro operacional líquido, Provisão para IR,
  reversão de JCP, etc.), mas o cross-foot do resultado líquido fica
  desligado nos anos anteriores a 2010 porque o fluxo publicado inclui
  linhas (PLR pré-tributação, reversão de JCP) que a equação IFRS não
  considera. Os cross-foots de BP continuam valendo.
- **Completude de OCR pré-2008** (brochuras 2001–2009): parte das linhas se
  perde por erros de reconhecimento de caracteres (`Móveis` → `Mózeis`,
  `Outros` → `Qutros`, `Investimento` → `i ti t`). O gate de materialidade
  rebaixa esses casos a avisos; para os documentos afetados, preencha
  `data/manual_overrides/<year>.yaml` com valores digitados à mão a partir
  do parecer dos auditores quando precisar de cobertura completa.
- **ITR 2023-Q2**: o PDF-fonte tem OCR com espaçamentos artificiais
  (`Propriedades para i ti t`); também rebaixado a aviso.
- **Cobertura DRE intermediária**: BP, DVA e DFC têm cobertura razoável
  desde 2008, mas a DRE só foi extraída integralmente em 2014 e a partir de
  2018. As demais safras dependem de melhorias no parser para os layouts
  antigos; até lá, as figuras-chave são preenchidas via
  `data/manual_overrides/<ano>.yaml` (com citação verbatim do PDF).

## Sobrescritas manuais (`data/manual_overrides/`)

Para valores que o pipeline automático não consegue recuperar (PDFs escaneados
com OCR ruim, layouts atípicos), use YAML por documento:

```yaml
source: "Relatório do Auditor Independente 2008"
sha256: "<hash do PDF da fonte>"
page: 3
url: "https://..."
vintage_year: 2008
currency_unit: thousands           # 'thousands' | 'millions' | 'units'
rows:
  - line_id: dre.receita_liquida
    period_year: 2008
    period_kind: fy
    value: 7494100                 # interpretado em currency_unit
    label_raw: "Receita líquida (auditor)"
```

Esses valores são incorporados ao canônico com `doc_id = manual:<arquivo>` e
participam de cross-foots e goldens normalmente.

## Reprodução completa

```bash
make clean      # remove data/interim, data/processed, data/site
make all        # fetch + extract + normalize + verify + site
```

Tempo total de execução em uma máquina razoavelmente moderna: ~30–40 minutos
no primeiro `make all` (dominado pela passagem de OCR sobre as ~30 brochuras
pré-2010). Execuções subsequentes reaproveitam o cache de OCR e levam alguns
minutos.

## Licença e fontes

O **código** deste projeto está licenciado sob a [ISC License](LICENSE) — uma
licença permissiva curta, equivalente em escopo à BSD-2-Clause / MIT. Você
pode usar, modificar e redistribuir livremente, mantendo o aviso de copyright.

Os **PDFs originais** são publicação oficial dos Correios (informação pública
sob a Lei de Acesso à Informação). Este repositório apenas reorganiza, indexa
e apresenta esses dados; não há contribuição editorial ou opinião sobre os
números reportados.

Os **dados extraídos** não devem ser usados como substituto das fontes
oficiais — são uma transformação reproduzível mas que pode conter erros de
extração (especialmente em brochuras escaneadas pré-2010). Sempre confira
contra o PDF-fonte; cada figura no site tem link de retorno para a página
específica do relatório.
