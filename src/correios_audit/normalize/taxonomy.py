"""
Canonical chart of accounts for Correios financial statements.

`line_id` is the stable identifier downstream artifacts reference. The hierarchy
is encoded in the dotted name (`bp.passivo.nao_circulante.beneficios_pos_emprego`).
`parent` lets the renderer compute totals and indent.

`valid_from` / `valid_to` capture the BR-GAAP → IFRS transition (~2008–2010): some
lines (DOAR) only existed pre-IFRS, others (DRA, DFC) only post-IFRS. `sign` tells
the verifier whether values should be positive (assets, revenues) or negative
(losses, costs as published).

Statements covered here for the initial slice: BP, DRE, DFC, DVA. DMPL, DRA, and
notes (pension, contingencies, segments) are added in later mapping waves.

Edit this file when a real PDF reveals a line we haven't named yet. Don't add
synthetic placeholders — every line_id must correspond to something we've seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Statement = Literal["bp", "dre", "dra", "dfc", "dva", "dmpl"]
SECTION_LABEL = "section"
Sign = Literal["+", "-", "any"]


@dataclass(frozen=True)
class Line:
    line_id: str
    statement: Statement
    label_pt: str
    parent: str | None = None
    sign: Sign = "any"
    is_total: bool = False
    valid_from: int = 2001
    valid_to: int = 2099


# --- Balanço Patrimonial (BP) --------------------------------------------------

BP_LINES: tuple[Line, ...] = (
    # ATIVO
    Line("bp.ativo", "bp", "ATIVO", is_total=True),
    Line("bp.ativo.circulante", "bp", "Ativo circulante", parent="bp.ativo", is_total=True),
    Line("bp.ativo.circulante.caixa_equivalentes", "bp",
         "Caixa e equivalentes de caixa", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.aplicacoes", "bp",
         "Aplicações financeiras", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.contas_a_receber", "bp",
         "Contas a receber", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.estoques", "bp",
         "Estoques", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.outros_valores_e_bens", "bp",
         "Outros valores e bens", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.tributos_a_compensar", "bp",
         "Tributos a compensar", parent="bp.ativo.circulante",
         valid_from=2008),

    Line("bp.ativo.nao_circulante", "bp",
         "Ativo não circulante", parent="bp.ativo", is_total=True),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo", "bp",
         "Realizável a longo prazo", parent="bp.ativo.nao_circulante", is_total=True),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.contas_a_receber", "bp",
         "Contas a receber (LP)", parent="bp.ativo.nao_circulante.realizavel_longo_prazo"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.aplicacoes", "bp",
         "Aplicações (LP)", parent="bp.ativo.nao_circulante.realizavel_longo_prazo"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.tributos_diferidos", "bp",
         "Tributos diferidos", parent="bp.ativo.nao_circulante.realizavel_longo_prazo"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.depositos_judiciais", "bp",
         "Depósitos judiciais e administrativos",
         parent="bp.ativo.nao_circulante.realizavel_longo_prazo"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.tributos_a_compensar", "bp",
         "Tributos a compensar (LP)",
         parent="bp.ativo.nao_circulante.realizavel_longo_prazo"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.outros", "bp",
         "Outros valores e bens (LP)",
         parent="bp.ativo.nao_circulante.realizavel_longo_prazo"),
    Line("bp.ativo.nao_circulante.investimentos", "bp",
         "Investimentos", parent="bp.ativo.nao_circulante"),
    Line("bp.ativo.nao_circulante.imobilizado", "bp",
         "Imobilizado", parent="bp.ativo.nao_circulante"),
    Line("bp.ativo.nao_circulante.intangivel", "bp",
         "Intangível", parent="bp.ativo.nao_circulante"),

    Line("bp.ativo.total", "bp", "Total do ativo", parent="bp.ativo", is_total=True),

    # PASSIVO
    Line("bp.passivo", "bp", "PASSIVO", is_total=True),
    Line("bp.passivo.circulante", "bp",
         "Passivo circulante", parent="bp.passivo", is_total=True),
    Line("bp.passivo.circulante.fornecedores", "bp",
         "Fornecedores", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.beneficios_a_empregados", "bp",
         "Benefícios a empregados (CP)", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.impostos_a_pagar", "bp",
         "Impostos e contribuições", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.arrecadacoes_recebimentos", "bp",
         "Arrecadações e recebimentos", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.adiantamentos_clientes", "bp",
         "Adiantamentos de clientes e receitas a apropriar",
         parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.contas_internacionais", "bp",
         "Contas internacionais (CP)", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.processos_judiciais", "bp",
         "Processos judiciais (CP)", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.emprestimos", "bp",
         "Empréstimos e financiamentos (CP)", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.arrendamento", "bp",
         "Arrendamento (CP)", parent="bp.passivo.circulante", valid_from=2019),
    Line("bp.passivo.circulante.derivativos", "bp",
         "Instrumentos financeiros - derivativos (CP)",
         parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.outros", "bp",
         "Outros créditos (CP)", parent="bp.passivo.circulante"),

    Line("bp.passivo.nao_circulante", "bp",
         "Passivo não circulante", parent="bp.passivo", is_total=True),
    Line("bp.passivo.nao_circulante.contas_internacionais", "bp",
         "Contas internacionais (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.nao_circulante.adiantamentos_clientes", "bp",
         "Adiantamentos de clientes (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.nao_circulante.beneficios_pos_emprego", "bp",
         "Benefícios pós-emprego (Postalis e saúde)",
         parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.nao_circulante.tributos_diferidos", "bp",
         "Tributos diferidos (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.nao_circulante.processos_judiciais", "bp",
         "Processos judiciais (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.nao_circulante.arrendamento", "bp",
         "Arrendamento (LP)", parent="bp.passivo.nao_circulante", valid_from=2019),
    Line("bp.passivo.nao_circulante.outros", "bp",
         "Outros créditos (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.nao_circulante.emprestimos", "bp",
         "Empréstimos e financiamentos (LP)",
         parent="bp.passivo.nao_circulante"),

    Line("bp.patrimonio_liquido", "bp",
         "Patrimônio líquido", parent="bp.passivo", is_total=True),
    Line("bp.patrimonio_liquido.capital", "bp",
         "Capital social", parent="bp.patrimonio_liquido"),
    Line("bp.patrimonio_liquido.aap", "bp",
         "Ajuste de avaliação patrimonial", parent="bp.patrimonio_liquido"),
    Line("bp.patrimonio_liquido.ora", "bp",
         "Outros resultados abrangentes", parent="bp.patrimonio_liquido",
         valid_from=2010),
    Line("bp.patrimonio_liquido.reservas", "bp",
         "Reservas de lucros", parent="bp.patrimonio_liquido"),
    Line("bp.patrimonio_liquido.lucros_prejuizos_acumulados", "bp",
         "Lucros / prejuízos acumulados", parent="bp.patrimonio_liquido"),

    Line("bp.passivo.total", "bp",
         "Total do passivo e patrimônio líquido", parent="bp.passivo", is_total=True),
)


# --- DRE ------------------------------------------------------------------------

DRE_LINES: tuple[Line, ...] = (
    Line("dre.receita_bruta", "dre", "Receita operacional bruta", sign="+"),
    Line("dre.deducoes", "dre", "Deduções da receita bruta", sign="-"),
    Line("dre.receita_liquida", "dre", "Receita líquida", sign="+", is_total=True),
    Line("dre.cpv", "dre", "Custo dos produtos/serviços", sign="-"),
    Line("dre.lucro_bruto", "dre", "Lucro bruto", is_total=True),
    Line("dre.despesas_vendas", "dre", "Despesas com vendas/serviços", sign="-"),
    Line("dre.despesas_administrativas", "dre",
         "Despesas gerais e administrativas", sign="-"),
    Line("dre.outras_receitas_operacionais", "dre", "Outras receitas operacionais"),
    Line("dre.outras_despesas_operacionais", "dre", "Outras despesas operacionais", sign="-"),
    Line("dre.resultado_operacional", "dre",
         "Resultado operacional (antes do financeiro)", is_total=True),
    Line("dre.receitas_financeiras", "dre", "Receitas financeiras", sign="+"),
    Line("dre.despesas_financeiras", "dre", "Despesas financeiras", sign="-"),
    Line("dre.resultado_financeiro", "dre", "Resultado financeiro", is_total=True),
    Line("dre.resultado_antes_ir", "dre", "Resultado antes dos tributos", is_total=True),
    Line("dre.tributos_sobre_lucro", "dre",
         "Tributos sobre o lucro (IRPJ/CSLL)"),
    Line("dre.resultado_liquido", "dre",
         "Resultado líquido do período", is_total=True),
)


# --- DFC ------------------------------------------------------------------------

DFC_LINES: tuple[Line, ...] = (
    Line("dfc.atividades_operacionais", "dfc", "Atividades operacionais", is_total=True),
    Line("dfc.op.resultado_periodo", "dfc",
         "Resultado do período", parent="dfc.atividades_operacionais"),
    Line("dfc.op.itens_nao_caixa", "dfc",
         "Itens do resultado que não afetam o caixa",
         parent="dfc.atividades_operacionais", is_total=True),
    Line("dfc.op.itens_nao_caixa.depreciacao_amortizacao", "dfc",
         "Depreciação e amortização",
         parent="dfc.op.itens_nao_caixa"),
    Line("dfc.op.itens_nao_caixa.provisoes", "dfc",
         "Provisões", parent="dfc.op.itens_nao_caixa"),
    Line("dfc.op.mutacoes_patrimoniais", "dfc",
         "Variações de ativos e passivos",
         parent="dfc.atividades_operacionais", is_total=True),
    Line("dfc.op.recursos_liquidos", "dfc",
         "Caixa líquido das atividades operacionais",
         parent="dfc.atividades_operacionais", is_total=True),

    Line("dfc.atividades_investimento", "dfc",
         "Atividades de investimento", is_total=True),
    Line("dfc.inv.imobilizado_adicoes", "dfc",
         "Adições ao imobilizado", parent="dfc.atividades_investimento", sign="-"),
    Line("dfc.inv.intangivel_adicoes", "dfc",
         "Adições ao intangível", parent="dfc.atividades_investimento", sign="-"),
    Line("dfc.inv.aplicacoes_financeiras", "dfc",
         "Aplicações financeiras (líquido)", parent="dfc.atividades_investimento"),
    Line("dfc.inv.recursos_liquidos", "dfc",
         "Caixa líquido das atividades de investimento",
         parent="dfc.atividades_investimento", is_total=True),

    Line("dfc.atividades_financiamento", "dfc",
         "Atividades de financiamento", is_total=True),
    Line("dfc.fin.captacoes", "dfc",
         "Captações de empréstimos",
         parent="dfc.atividades_financiamento", sign="+"),
    Line("dfc.fin.amortizacoes", "dfc",
         "Amortizações de empréstimos (principal+juros)",
         parent="dfc.atividades_financiamento", sign="-"),
    Line("dfc.fin.arrendamento", "dfc",
         "Pagamentos de arrendamento (principal+juros)",
         parent="dfc.atividades_financiamento", sign="-",
         valid_from=2019),
    Line("dfc.fin.recursos_liquidos", "dfc",
         "Caixa líquido das atividades de financiamento",
         parent="dfc.atividades_financiamento", is_total=True),

    Line("dfc.variacao_caixa", "dfc",
         "Variação líquida de caixa e equivalentes", is_total=True),
    Line("dfc.caixa_inicio", "dfc", "Caixa e equivalentes no início do período"),
    Line("dfc.caixa_fim", "dfc", "Caixa e equivalentes no fim do período"),
)


# --- DVA ------------------------------------------------------------------------

DVA_LINES: tuple[Line, ...] = (
    Line("dva.receitas", "dva", "Receitas", is_total=True),
    Line("dva.insumos", "dva", "Insumos adquiridos de terceiros", sign="-", is_total=True),
    Line("dva.va_bruto", "dva", "Valor adicionado bruto", is_total=True),
    Line("dva.retencoes", "dva", "Retenções (depreciação/amortização)", sign="-"),
    Line("dva.va_liquido", "dva",
         "Valor adicionado líquido produzido pela entidade", is_total=True),
    Line("dva.va_recebido_transferencia", "dva", "Valor adicionado recebido em transferência"),
    Line("dva.va_total_distribuir", "dva", "Valor adicionado total a distribuir", is_total=True),
    Line("dva.dist.trabalho", "dva", "Distribuído ao trabalho (pessoal)", is_total=True),
    Line("dva.dist.governo", "dva", "Distribuído ao governo (impostos)", is_total=True),
    Line("dva.dist.terceiros", "dva", "Distribuído ao capital de terceiros", is_total=True),
    Line("dva.dist.acionistas", "dva", "Distribuído aos acionistas (lucros retidos)",
         is_total=True),
    Line("dva.total_distribuido", "dva", "Total distribuído", is_total=True),
)


# --- DRA (Demonstração do Resultado Abrangente) -------------------------------

DRA_LINES: tuple[Line, ...] = (
    Line("dra.resultado_liquido", "dra", "Resultado líquido do período",
         valid_from=2010, is_total=True),
    Line("dra.itens_nao_reclassificaveis", "dra",
         "Itens que não serão reclassificados para o resultado",
         valid_from=2010, is_total=True),
    Line("dra.itens_nao_reclassificaveis.beneficios_pos_emprego", "dra",
         "Remensuração de obrigações de benefícios pós-emprego",
         parent="dra.itens_nao_reclassificaveis", valid_from=2010),
    Line("dra.itens_nao_reclassificaveis.investimentos_vjora", "dra",
         "Ganho/perda em investimentos a valor justo (VJORA)",
         parent="dra.itens_nao_reclassificaveis", valid_from=2010),
    Line("dra.itens_nao_reclassificaveis.imoveis", "dra",
         "Realização do ganho pela venda de imóvel / propriedades",
         parent="dra.itens_nao_reclassificaveis", valid_from=2010),
    Line("dra.itens_nao_reclassificaveis.csll_diferida", "dra",
         "CSLL diferida sobre itens não reclassificáveis",
         parent="dra.itens_nao_reclassificaveis", valid_from=2010),
    Line("dra.itens_reclassificaveis", "dra",
         "Itens que serão reclassificados para o resultado",
         valid_from=2010, is_total=True),
    Line("dra.resultado_abrangente_total", "dra",
         "Resultado abrangente total do período",
         valid_from=2010, is_total=True),
)


# --- Extended DFC sub-items ---------------------------------------------------

DFC_EXTENDED_LINES: tuple[Line, ...] = (
    Line("dfc.op.itens_nao_caixa.outros", "dfc",
         "Outros ajustes não-caixa (variações patrimoniais, valor justo, alienações)",
         parent="dfc.op.itens_nao_caixa"),
    Line("dfc.op.mutacoes.contas_receber", "dfc",
         "Mutação - Contas a receber", parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.estoques", "dfc",
         "Mutação - Estoques", parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.outros_ativos", "dfc",
         "Mutação - Outros valores e bens",
         parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.realizavel_lp", "dfc",
         "Mutação - Realizável a longo prazo",
         parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.fornecedores", "dfc",
         "Mutação - Fornecedores", parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.salarios", "dfc",
         "Mutação - Salários e encargos sociais",
         parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.impostos", "dfc",
         "Mutação - Impostos e contribuições",
         parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.op.mutacoes.outras", "dfc",
         "Mutação - Outras (saúde, IFD, contas internacionais, etc.)",
         parent="dfc.op.mutacoes_patrimoniais"),
    Line("dfc.inv.imobilizado_baixas", "dfc",
         "Baixas de imobilizado", parent="dfc.atividades_investimento"),
    Line("dfc.inv.propriedades_investimento", "dfc",
         "Propriedades para investimento (adições/baixas)",
         parent="dfc.atividades_investimento"),
    Line("dfc.fin.juros_pagos", "dfc",
         "Juros pagos sobre empréstimos/arrendamento",
         parent="dfc.atividades_financiamento", sign="-"),
)


# --- Extended DVA sub-items ---------------------------------------------------

DVA_EXTENDED_LINES: tuple[Line, ...] = (
    Line("dva.receitas.operacionais", "dva",
         "Receitas operacionais", parent="dva.receitas"),
    Line("dva.receitas.pdd", "dva",
         "Perda/reversão de crédito de liquidação duvidosa", parent="dva.receitas"),
    Line("dva.receitas.outras", "dva",
         "Outras receitas operacionais (DVA)", parent="dva.receitas"),
    Line("dva.insumos.cpv", "dva",
         "Custo dos serviços prestados e produtos vendidos (DVA)",
         parent="dva.insumos"),
    Line("dva.insumos.servicos_terceiros", "dva",
         "Serviços adquiridos de terceiros", parent="dva.insumos"),
    Line("dva.insumos.provisoes", "dva",
         "Provisões diversas (DVA)", parent="dva.insumos"),
    Line("dva.insumos.outros", "dva",
         "Materiais consumidos / outros insumos", parent="dva.insumos"),
    Line("dva.retencoes.depreciacao", "dva",
         "Depreciação/amortização (DVA)", parent="dva.retencoes"),
    Line("dva.va_recebido_transferencia.financeiras", "dva",
         "Receitas financeiras (DVA)", parent="dva.va_recebido_transferencia"),
    Line("dva.dist.trabalho.salarios", "dva",
         "Salários, honorários e benefícios", parent="dva.dist.trabalho"),
    Line("dva.dist.trabalho.encargos", "dva",
         "Encargos sociais", parent="dva.dist.trabalho"),
    Line("dva.dist.governo.inss", "dva", "INSS", parent="dva.dist.governo"),
    Line("dva.dist.governo.outros", "dva",
         "Outros impostos e contribuições", parent="dva.dist.governo"),
    Line("dva.dist.terceiros.alugueis_juros", "dva",
         "Aluguéis, juros, variação cambial", parent="dva.dist.terceiros"),
    Line("dva.dist.terceiros.outras", "dva",
         "Outras remunerações a terceiros", parent="dva.dist.terceiros"),
    Line("dva.dist.acionistas.lucros_retidos", "dva",
         "Lucros / prejuízos retidos", parent="dva.dist.acionistas"),
)


# --- Sub-items that appear in older annuals or 2018-2022 quarterlies --------
# Older statements often split lines into more granular categories than IFRS-era
# annuals. We expose these as additional canonical line_ids so the data isn't
# lost. They overlap conceptually with the parent line but at finer detail.

BP_LEGACY_LINES: tuple[Line, ...] = (
    # Pre-IFRS BR-GAAP layouts split caixa equivalentes into "Disponível"
    # with subitems "Caixa", "Bancos", "Aplicações". These map to the modern
    # caixa_equivalentes parent but are also kept as their own line_ids so
    # the older-period data isn't silently aggregated away.
    Line("bp.ativo.disponivel", "bp", "Disponível (BR-GAAP)",
         parent="bp.ativo.circulante", valid_to=2010),
    Line("bp.ativo.circulante.caixa_equivalentes.caixa", "bp",
         "Caixa", parent="bp.ativo.circulante.caixa_equivalentes"),
    Line("bp.ativo.circulante.caixa_equivalentes.bancos", "bp",
         "Bancos", parent="bp.ativo.circulante.caixa_equivalentes"),
    Line("bp.ativo.circulante.caixa_equivalentes.aplicacoes", "bp",
         "Aplicações de liquidez imediata",
         parent="bp.ativo.circulante.caixa_equivalentes"),
    Line("bp.ativo.circulante.caixa_restrito", "bp",
         "Caixa restrito", parent="bp.ativo.circulante"),
    # Pre-IFRS "Permanente" was Investimentos + Imobilizado + Intangível +
    # Diferido. We keep it as a legacy parent for the years it appears.
    Line("bp.ativo.permanente", "bp", "Permanente (BR-GAAP)",
         parent="bp.ativo.nao_circulante", is_total=True, valid_to=2010),
    Line("bp.ativo.permanente.diferido", "bp",
         "Diferido (BR-GAAP)", parent="bp.ativo.permanente", valid_to=2010),
    # Resultados de exercícios futuros — pre-IFRS only.
    Line("bp.passivo.resultados_exercicios_futuros", "bp",
         "Resultados de exercícios futuros (BR-GAAP)",
         parent="bp.passivo", valid_to=2010),
    # Imóveis funcionais (vendidos) — RLP entry in 2010-2018 BPs.
    Line("bp.ativo.nao_circulante.imobilizado.imoveis_funcionais", "bp",
         "Imóveis funcionais (vendidos)",
         parent="bp.ativo.nao_circulante.imobilizado"),
    # Outras aplicações VJORA — RLP financial instruments at fair value.
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.outras_aplicacoes_vjora",
         "bp", "Outras aplicações – VJORA",
         parent="bp.ativo.nao_circulante.realizavel_longo_prazo",
         valid_from=2018),
    # Investimento minoritário em CorreiosPar (subsidiary).
    Line("bp.ativo.nao_circulante.investimentos.correiospar", "bp",
         "Correiospar", parent="bp.ativo.nao_circulante.investimentos"),
    # Obrigações financeiras a pagar — separate from empréstimos in 2014-2019.
    Line("bp.passivo.circulante.obrigacoes_financeiras", "bp",
         "Obrigações financeiras a pagar (CP)",
         parent="bp.passivo.circulante"),
    Line("bp.passivo.nao_circulante.obrigacoes_financeiras", "bp",
         "Obrigações financeiras a pagar (LP)",
         parent="bp.passivo.nao_circulante"),
    # Convênio Postal Saúde on the passivo CIRCULANTE side (not just LP).
    Line("bp.passivo.circulante.convenio_saude", "bp",
         "Convênio Postal Saúde (CP)",
         parent="bp.passivo.circulante"),
    # AFAC (Adiantamento para Futuro Aumento de Capital) — non-PL transitional
    # account that sits between passivo and PL in some years.
    Line("bp.patrimonio_liquido.afac", "bp",
         "Adiantamento para futuro aumento de capital (AFAC)",
         parent="bp.patrimonio_liquido"),
    # IFRS 16 right-of-use breakdown — separate line for the depreciation
    # of imóveis de direito de uso (often shown distinct from regular
    # depreciation in the 2019+ BPs).
    Line("bp.ativo.nao_circulante.imobilizado.bens_direito_uso.depreciacao",
         "bp", "(-) Depreciação de imóveis de direito de uso",
         parent="bp.ativo.nao_circulante.imobilizado.bens_direito_uso",
         sign="-", valid_from=2019),
    # Passivo de direito de uso (CP and LP) — alias of arrendamento,
    # carried as its own line_id since some BPs publish them side-by-side.
    Line("bp.passivo.circulante.passivo_direito_uso", "bp",
         "Passivo por direito de uso (CP, IFRS 16)",
         parent="bp.passivo.circulante", valid_from=2019),
    Line("bp.passivo.nao_circulante.passivo_direito_uso", "bp",
         "Passivo por direito de uso (LP, IFRS 16)",
         parent="bp.passivo.nao_circulante", valid_from=2019),
    # AAP sub-detail: bens em uso vs mantidos para venda. Older BPs split.
    Line("bp.patrimonio_liquido.aap.bens_em_uso", "bp",
         "AAP - bens em uso", parent="bp.patrimonio_liquido.aap"),
    Line("bp.patrimonio_liquido.aap.bens_mantidos_venda", "bp",
         "AAP - bens mantidos para venda",
         parent="bp.patrimonio_liquido.aap"),
    # Reservas de lucros sub-categories.
    Line("bp.patrimonio_liquido.reservas.legal", "bp",
         "Reserva legal", parent="bp.patrimonio_liquido.reservas"),
    Line("bp.patrimonio_liquido.reservas.lucros_realizar", "bp",
         "Reserva de lucros a realizar",
         parent="bp.patrimonio_liquido.reservas"),
    Line("bp.patrimonio_liquido.reservas.investimento", "bp",
         "Reserva para projeto de investimento",
         parent="bp.patrimonio_liquido.reservas"),
    Line("bp.patrimonio_liquido.reservas.estatutaria", "bp",
         "Reserva estatutária", parent="bp.patrimonio_liquido.reservas"),
    Line("bp.patrimonio_liquido.dividendo_adicional", "bp",
         "Dividendo adicional proposto",
         parent="bp.patrimonio_liquido"),
)


BP_SUBITEM_LINES: tuple[Line, ...] = (
    Line("bp.ativo.circulante.titulos_valores_mobiliarios", "bp",
         "Títulos e valores mobiliários", parent="bp.ativo.circulante",
         valid_to=2022),
    Line("bp.ativo.circulante.contas_a_receber.nacionais", "bp",
         "Contas a receber - nacionais",
         parent="bp.ativo.circulante.contas_a_receber"),
    Line("bp.ativo.circulante.contas_a_receber.internacionais", "bp",
         "Contas a receber - internacionais",
         parent="bp.ativo.circulante.contas_a_receber"),
    Line("bp.ativo.circulante.adiantamento_pessoal", "bp",
         "Adiantamento de pessoal", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.convenio_postal_saude", "bp",
         "Convênio Postal Saúde (a receber)", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.cobranca_juridica", "bp",
         "Cobrança jurídica/inadimplência", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.despesas_antecipadas", "bp",
         "Despesas antecipadas", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.adiantamentos_diversos", "bp",
         "Adiantamentos diversos", parent="bp.ativo.circulante"),
    Line("bp.ativo.circulante.valores_apurar", "bp",
         "Valores a apurar", parent="bp.ativo.circulante"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.contas_a_receber.nacionais", "bp",
         "Contas a receber LP - nacionais",
         parent="bp.ativo.nao_circulante.realizavel_longo_prazo.contas_a_receber"),
    Line("bp.ativo.nao_circulante.realizavel_longo_prazo.contas_a_receber.internacionais",
         "bp", "Contas a receber LP - internacionais",
         parent="bp.ativo.nao_circulante.realizavel_longo_prazo.contas_a_receber"),
    Line("bp.ativo.nao_circulante.propriedades_investimento", "bp",
         "Propriedades para investimento (separate line in 2014-2022 layouts)",
         parent="bp.ativo.nao_circulante", valid_to=2022),
    Line("bp.ativo.nao_circulante.museu", "bp",
         "Acervo museológico", parent="bp.ativo.nao_circulante"),

    Line("bp.passivo.circulante.salarios_consignacoes", "bp",
         "Salários e consignações", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.encargos_sociais", "bp",
         "Encargos sociais", parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.precatorios", "bp",
         "Precatórios (CP)", parent="bp.passivo.circulante"),
    Line("bp.passivo.nao_circulante.precatorios", "bp",
         "Precatórios (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.circulante.transferencias_uniao", "bp",
         "Transferências para a União (dividendos/JCP a pagar)",
         parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.participacao_lucros", "bp",
         "Participação nos Lucros e Resultados (PLR/RVA)",
         parent="bp.passivo.circulante"),
    Line("bp.passivo.circulante.dividendos_a_pagar", "bp",
         "Dividendos a pagar", parent="bp.passivo.circulante"),
    Line("bp.passivo.nao_circulante.convenio_saude", "bp",
         "Convênio Postal Saúde (LP)", parent="bp.passivo.nao_circulante"),
    Line("bp.passivo.circulante.outros_debitos", "bp",
         "Outros débitos (CP)", parent="bp.passivo.circulante"),

    # Imobilizado breakdown (sub-categories of bp.ativo.nao_circulante.imobilizado).
    # Older BPs split this; modern ones aggregate.
    Line("bp.ativo.nao_circulante.imobilizado.imoveis", "bp",
         "Imóveis", parent="bp.ativo.nao_circulante.imobilizado"),
    Line("bp.ativo.nao_circulante.imobilizado.moveis", "bp",
         "Móveis e equipamentos", parent="bp.ativo.nao_circulante.imobilizado"),
    Line("bp.ativo.nao_circulante.imobilizado.arrendamento", "bp",
         "Imóveis - arrendamento (right-of-use, IFRS 16)",
         parent="bp.ativo.nao_circulante.imobilizado", valid_from=2019),
    Line("bp.ativo.nao_circulante.imobilizado.depreciacao", "bp",
         "(-) Depreciação acumulada",
         parent="bp.ativo.nao_circulante.imobilizado", sign="-"),
    Line("bp.ativo.nao_circulante.imobilizado.bens_direito_uso", "bp",
         "Bens de direito de uso (IFRS 16)",
         parent="bp.ativo.nao_circulante.imobilizado", valid_from=2019),
    Line("bp.ativo.nao_circulante.outros_mantido_venda", "bp",
         "Não circulante mantido para venda",
         parent="bp.ativo.nao_circulante"),
)

DRE_SUBITEM_LINES: tuple[Line, ...] = (
    Line("dre.tributos_sobre_lucro.correntes", "dre",
         "Tributos correntes (IRPJ + CSLL)", parent="dre.tributos_sobre_lucro"),
    Line("dre.tributos_sobre_lucro.diferidos", "dre",
         "Tributos diferidos (IRPJ + CSLL)", parent="dre.tributos_sobre_lucro"),
    Line("dre.resultado_participacao_controlada", "dre",
         "Resultado de participação em controlada (equity method)"),
    # Sub-categories of dre.tributos_sobre_lucro that pre-IFRS DREs name
    # explicitly ("Provisão para imposto de renda" / "Provisão para a
    # contribuição social"). Modern DREs aggregate them.
    Line("dre.tributos_sobre_lucro.irpj", "dre",
         "Provisão para imposto de renda (IRPJ)",
         parent="dre.tributos_sobre_lucro", valid_to=2010),
    Line("dre.tributos_sobre_lucro.csll", "dre",
         "Provisão para a contribuição social (CSLL)",
         parent="dre.tributos_sobre_lucro", valid_to=2010),
    # Pre-IFRS "Lucro Operacional Líquido" — distinct from the modern
    # "Resultado operacional antes do financeiro".
    Line("dre.lucro_operacional_liquido", "dre",
         "Lucro operacional líquido (BR-GAAP)",
         is_total=True, valid_to=2010),
    # PLR appears as a separate DRE line pre-2010 (between tax and net income).
    Line("dre.participacao_lucros", "dre",
         "Participação nos lucros e resultados (PLR)", sign="-"),
    # Juros sobre capital próprio — pre-IFRS DRE adjustment (added back below
    # net income in older Correios layouts).
    Line("dre.juros_capital_proprio", "dre",
         "Juros sobre capital próprio (JCP)", valid_to=2010),
    Line("dre.reversao_jcp", "dre",
         "Reversão de juros sobre capital próprio", valid_to=2010),
    # Pre-IFRS "Receitas / Despesas não-operacionais" — eliminated by IFRS
    # but appears in 2001-2009 DREs.
    Line("dre.receitas_nao_operacionais", "dre",
         "Receitas não-operacionais (BR-GAAP)", valid_to=2010),
    Line("dre.despesas_nao_operacionais", "dre",
         "Despesas não-operacionais (BR-GAAP)", sign="-", valid_to=2010),
    # Pre-IFRS provisões line (between resultado pre-tributos and tributos).
    Line("dre.provisoes", "dre",
         "Provisões (BR-GAAP)", valid_to=2010),
    Line("dre.resultado_antes_provisoes", "dre",
         "Resultado antes das provisões (BR-GAAP)",
         is_total=True, valid_to=2010),
    Line("dre.resultado_antes_plr", "dre",
         "Resultado antes da PLR (BR-GAAP)",
         is_total=True, valid_to=2010),
    Line("dre.resultado_antes_jcp", "dre",
         "Resultado antes dos juros sobre capital próprio",
         is_total=True, valid_to=2010),
    # Pre-IFRS "Despesas operacionais" parent.
    Line("dre.despesas_operacionais", "dre",
         "Despesas operacionais (BR-GAAP)",
         is_total=True, valid_to=2010),
    Line("dre.despesas_operacionais.financeiras", "dre",
         "Despesas financeiras (sub of despesas operacionais)",
         parent="dre.despesas_operacionais", valid_to=2010),
    Line("dre.receitas_operacionais", "dre",
         "Receitas operacionais (BR-GAAP, parent)",
         is_total=True, valid_to=2010),
    Line("dre.receitas_operacionais.financeiras", "dre",
         "Receitas financeiras (sub of receitas operacionais)",
         parent="dre.receitas_operacionais", valid_to=2010),
    # Sub-detail of administrative expenses sometimes published separately.
    Line("dre.despesas_administrativas.depreciacao_amortizacao", "dre",
         "Despesas de depreciação e amortização",
         parent="dre.despesas_administrativas"),
    Line("dre.deducoes.impostos", "dre",
         "Impostos e contribuições sobre a receita",
         parent="dre.deducoes"),
    Line("dre.deducoes.canceladas", "dre",
         "Receitas canceladas / abatimentos",
         parent="dre.deducoes"),
)

DRA_SUBITEM_LINES: tuple[Line, ...] = (
    Line("dra.itens_nao_reclassificaveis.csll_remensuracao", "dra",
         "CSLL diferida sobre remensuração de pós-emprego",
         parent="dra.itens_nao_reclassificaveis", valid_from=2010),
)


ALL_LINES: tuple[Line, ...] = (
    BP_LINES + BP_SUBITEM_LINES + BP_LEGACY_LINES
    + DRE_LINES + DRE_SUBITEM_LINES
    + DRA_LINES + DRA_SUBITEM_LINES
    + DFC_LINES + DFC_EXTENDED_LINES
    + DVA_LINES + DVA_EXTENDED_LINES
)
LINES_BY_ID: dict[str, Line] = {ln.line_id: ln for ln in ALL_LINES}


def by_statement(statement: Statement) -> tuple[Line, ...]:
    return tuple(ln for ln in ALL_LINES if ln.statement == statement)


if __name__ == "__main__":
    from collections import Counter

    by_st = Counter(ln.statement for ln in ALL_LINES)
    print(f"Canonical taxonomy: {len(ALL_LINES)} lines")
    for st, n in sorted(by_st.items()):
        print(f"  {st}: {n}")
    # Quick consistency: every parent must exist
    ids = {ln.line_id for ln in ALL_LINES}
    bad = [ln for ln in ALL_LINES if ln.parent and ln.parent not in ids]
    if bad:
        print(f"\nBROKEN parents: {[ln.line_id for ln in bad]}")
    else:
        print("All parents resolve.")
