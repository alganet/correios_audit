"""
Static registry of all Correios financial-disclosure PDFs.

This is the canonical doc list. Each entry has a stable `doc_id` that downstream
artifacts (manifests, parquet rows, site URLs) reference. URLs are exactly as
published; some lack a .pdf extension because Plone serves them via redirect.
The fetcher follows redirects and content-sniffs the response.

doc_id grammar:
    <year>-<period>-<kind>[-<lang>]
    period:  fy | q1 | q2 | q3
    kind:    df | audit | cf      (financial statement / auditor / Conselho Fiscal)
    lang:    en                    (only for non-default English versions)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Period = Literal["fy", "q1", "q2", "q3"]
Kind = Literal["df", "audit", "cf"]
Lang = Literal["pt", "en"]


@dataclass(frozen=True)
class Doc:
    doc_id: str
    year: int
    period: Period
    kind: Kind
    url: str
    lang: Lang = "pt"

    @property
    def filename_hint(self) -> str:
        suffix = "" if self.lang == "pt" else f"-{self.lang}"
        return f"{self.doc_id}{suffix}"


_BASE = (
    "https://www.correios.com.br/acesso-a-informacao/institucional/publicacoes/"
    "demonstracoes-financeiras"
)


def _d(doc_id: str, year: int, period: Period, kind: Kind, path: str, lang: Lang = "pt") -> Doc:
    return Doc(doc_id=doc_id, year=year, period=period, kind=kind, url=f"{_BASE}/{path}", lang=lang)


# Order: most recent first (preferred when iterating for a sample).
DOCS: tuple[Doc, ...] = (
    # ---- 2025 ----
    _d("2025-q1-df", 2025, "q1", "df",
       "2025/demonstracoes_contabeis_correios_1trim-2025-27-05-25.pdf"),
    _d("2025-q1-audit", 2025, "q1", "audit",
       "2025/relatorio_auditoria_independente-1trim2025.pdf"),
    _d("2025-q2-df", 2025, "q2", "df",
       "2025/demonstracoes_contabeis_correios_2trim_2025_v14.pdf"),
    _d("2025-q2-audit", 2025, "q2", "audit", "2025/dcf_2_trim_25_rai_a.pdf"),
    _d("2025-q3-df", 2025, "q3", "df",
       "2025/demonstracoes_contabeis_correios_3trim_2025.pdf"),
    _d("2025-q3-audit", 2025, "q3", "audit",
       "2025/rra_correios_3_trim_2025_assinado.pdf"),
    # ---- 2024 ----
    _d("2024-q1-df", 2024, "q1", "df", "2024/demonstracoes-contabeis-1o-trim-2024.pdf"),
    _d("2024-q1-audit", 2024, "q1", "audit",
       "2024/relatorio_auditoria_independente-1trim2024.pdf"),
    _d("2024-q2-df", 2024, "q2", "df",
       "2024/demonstracoes-contabeis-correios-2t-2024-v10-final.pdf"),
    _d("2024-q2-audit", 2024, "q2", "audit",
       "2024/relatorio-auditoria-independente-2trim-2024.pdf"),
    _d("2024-q3-df", 2024, "q3", "df",
       "2024/demonstracoes_contabeis_correios_3t2024.pdf"),
    _d("2024-q3-audit", 2024, "q3", "audit",
       "2024/relatorio_auditoria_independente-3trim2024.pdf"),
    _d("2024-fy-df", 2024, "fy", "df", "2024/demonstracoes_contabeis_correios_2024.pdf"),
    _d("2024-fy-audit", 2024, "fy", "audit", "2024/relatorio_auditoria_independente-2024.pdf"),
    _d("2024-fy-cf", 2024, "fy", "cf", "2024/parecer-do-conselho-fiscal-2024.pdf"),
    # ---- 2023 ----
    _d("2023-q1-df", 2023, "q1", "df", "2023/demonstracoes-contabeis-1trim-2023"),
    _d("2023-q1-audit", 2023, "q1", "audit", "2023/relatorio-auditoria-independente-1trim-2023"),
    _d("2023-q2-df", 2023, "q2", "df", "2023/demonstracoes-contabeis-2o-trim-2023"),
    _d("2023-q2-audit", 2023, "q2", "audit",
       "2023/relatorio-de-auditoria-independente-2o-trim-2023"),
    _d("2023-q3-df", 2023, "q3", "df", "2023/demonstracoes-contabeis-3trim2023.pdf"),
    _d("2023-q3-audit", 2023, "q3", "audit",
       "2023/relatorio-auditoria-independente-3trim2023.pdf"),
    _d("2023-fy-df", 2023, "fy", "df", "2023/demonstracoes-contabeis-correios-2023.pdf"),
    _d("2023-fy-audit", 2023, "fy", "audit", "2023/relatorio-auditoria-independente-2023.pdf"),
    _d("2023-fy-cf", 2023, "fy", "cf", "2023/parecer-cf-2023.pdf"),
    # ---- 2022 ----
    _d("2022-q1-df", 2022, "q1", "df", "2022/demonstracoes-contabeis-1trim-2022"),
    _d("2022-q1-audit", 2022, "q1", "audit",
       "2022/relatorio-de-auditoria-independente-1o-trim-2022"),
    _d("2022-q2-df", 2022, "q2", "df", "2022/demonstracoes-contabeis-2013-2o-trim-2022"),
    _d("2022-q2-audit", 2022, "q2", "audit",
       "2022/relatorio-de-auditoria-independente-2o-trim-2022"),
    _d("2022-q3-df", 2022, "q3", "df", "2022/demonstracoes-contabeis-3o-trim-2022"),
    _d("2022-q3-audit", 2022, "q3", "audit",
       "2022/relatorio-de-auditoria-independente-3o-trim-2022"),
    _d("2022-fy-df", 2022, "fy", "df", "2022/demonstracoes-contabeis-2013-2022"),
    _d("2022-fy-audit", 2022, "fy", "audit", "2022/relatorio-de-auditoria-independente-2022"),
    _d("2022-fy-cf", 2022, "fy", "cf", "2022/parecer-do-conselho-fiscal-2022"),
    # ---- 2021 ----
    _d("2021-q1-df", 2021, "q1", "df", "2021/demonstracoes-contabeis-1t2021"),
    _d("2021-q1-audit", 2021, "q1", "audit",
       "2021/relatorio-da-auditoria-independente-2013-1t2021.pdf"),
    _d("2021-q2-df", 2021, "q2", "df", "2021/demonstracoes-contabeis-2o-trim-2021"),
    _d("2021-q2-audit", 2021, "q2", "audit",
       "2021/relatorio-de-auditoria-independente-2o-trim-2021"),
    _d("2021-q3-df", 2021, "q3", "df", "2021/demonstracoes-contabeis-3o-trim-2021"),
    _d("2021-q3-audit", 2021, "q3", "audit",
       "2021/relatorio-de-auditoria-independente-3o-trim-2021"),
    _d("2021-fy-df", 2021, "fy", "df", "2021/demonstracoes-contabeis-2021"),
    _d("2021-fy-audit", 2021, "fy", "audit", "2021/relatorio-de-auditoria-independente-2021"),
    _d("2021-fy-cf", 2021, "fy", "cf", "2021/parecer-conselho-fiscal-2021.pdf"),
    # ---- 2020 ----
    _d("2020-q1-df", 2020, "q1", "df", "2020/demonstracoes-contabeis-1o-trim-2020"),
    _d("2020-q1-audit", 2020, "q1", "audit",
       "2020/relatorio-de-auditoria-independente-1o-trim-2020"),
    _d("2020-q2-df", 2020, "q2", "df", "2020/demonstracoes-contabeis-2o-trim-2020"),
    _d("2020-q2-audit", 2020, "q2", "audit",
       "2020/relatorio-de-auditoria-independente-2o-trim-2020"),
    _d("2020-q3-df", 2020, "q3", "df", "2020/demonstracoes-contabeis-3o-trim-2020"),
    _d("2020-q3-audit", 2020, "q3", "audit",
       "2020/relatorio-de-auditoria-independente-3o-trim-2020"),
    _d("2020-fy-df", 2020, "fy", "df", "2020/demonstracoes-contabeis-2020"),
    _d("2020-fy-audit", 2020, "fy", "audit", "2020/relatorio-de-auditoris-independente-2020"),
    _d("2020-fy-cf", 2020, "fy", "cf", "2020/parecer-do-conselho-fiscal-2020.pdf"),
    # ---- 2019 ----
    _d("2019-q1-df", 2019, "q1", "df",
       "2019/parecer-auditoria-independente-1o-trim-2019-editavel.pdf"),
    _d("2019-q2-df", 2019, "q2", "df",
       "2019/parecer-auditoria-independente-2013-2o-trim-2019-editavel.pdf"),
    _d("2019-q3-df", 2019, "q3", "df",
       "2019/parecer-auditoria-independente-2013-3o-trim-2019-editavel.pdf"),
    _d("2019-fy-df", 2019, "fy", "df", "2019/demonstracoes-contabeis-2019"),
    _d("2019-fy-audit", 2019, "fy", "audit",
       "2019/relatorio-do-auditor-independente-2019-editavel.pdf"),
    _d("2019-fy-cf", 2019, "fy", "cf", "2019/parecer-do-conselho-fiscal"),
    # ---- 2018 ----
    _d("2018-q1-df", 2018, "q1", "df", "2018/demonstracoes-financeiras-1o-trim-2018.pdf"),
    _d("2018-q1-audit", 2018, "q1", "audit", "2018/parecer-da-auditoria-1o-trim-2018-editavel"),
    _d("2018-q2-df", 2018, "q2", "df", "2018/demonstracoes-financeiras-2o-trim-2018.pdf"),
    _d("2018-q2-audit", 2018, "q2", "audit", "2018/parecer-da-auditoria-2o-trim-2018.pdf"),
    _d("2018-q3-df", 2018, "q3", "df", "2018/demonstracoes-financeiras-3o-trim-2018.pdf"),
    _d("2018-q3-audit", 2018, "q3", "audit", "2018/parecer-da-auditoria-3o-trim-2018.pdf"),
    _d("2018-fy-df", 2018, "fy", "df", "2018/demonstracoes-financeiras-2018"),
    _d("2018-fy-audit", 2018, "fy", "audit",
       "2018/parecer-auditoria-independente-2018-editavel.pdf"),
    _d("2018-fy-cf", 2018, "fy", "cf", "2018/parecer-do-conselho-fiscal-2018.pdf"),
    # ---- 2017 ----
    _d("2017-q1-df", 2017, "q1", "df", "2017/demonstracoes-financeiras-1o-trim-2017.pdf"),
    _d("2017-q1-audit", 2017, "q1", "audit", "2017/parecer-da-auditoria-1o-trim-2017.pdf"),
    _d("2017-q2-df", 2017, "q2", "df", "2017/parecer-da-auditoria-2o-trim-2017.pdf"),
    _d("2017-q2-audit", 2017, "q2", "audit", "2017/parecer-da-auditoria-2o-trim-2017.pdf"),
    _d("2017-q3-df", 2017, "q3", "df", "2017/demonstracoes-financeiras-3o-trim-2017.pdf"),
    _d("2017-q3-audit", 2017, "q3", "audit", "2017/parecer-da-auditoria-3o-trim-2017.pdf"),
    _d("2017-fy-df", 2017, "fy", "df", "2017/demonstracoes-financeiras-de-2017.pdf"),
    _d("2017-fy-audit", 2017, "fy", "audit", "2017/parecer-da-auditoria-2017.pdf"),
    _d("2017-fy-cf", 2017, "fy", "cf", "2017/parecer-do-conselho-fiscal-2017.pdf"),
    # ---- 2016 ----
    _d("2016-fy-df", 2016, "fy", "df", "2016/demonstracoes-financeiras-de-2016"),
    _d("2016-fy-audit", 2016, "fy", "audit", "2016/parecer-da-auditoria-2016"),
    _d("2016-fy-cf", 2016, "fy", "cf", "2016/parecer-do-conselho-fiscal-2016"),
    # ---- 2015 ----
    _d("2015-fy-df", 2015, "fy", "df", "2015/demonstracoes-financeiras-de-2015"),
    _d("2015-fy-audit", 2015, "fy", "audit", "2015/relatorio-da-auditoria-independente-de-2015"),
    _d("2015-fy-cf", 2015, "fy", "cf", "2015/parecer-do-conselho-fiscal-2015"),
    # ---- 2014 ----
    _d("2014-fy-df", 2014, "fy", "df", "2014/demonstracoes-financeiras-de-2014"),
    _d("2014-fy-audit", 2014, "fy", "audit", "2014/parecer-auditoria-independente-2014"),
    # ---- 2013 ----
    _d("2013-fy-df", 2013, "fy", "df", "2013/demonstracoes-financeiras-de-2013"),
    _d("2013-fy-audit", 2013, "fy", "audit", "2013/parecer-auditoria-independente-2013"),
    # ---- 2012 ----
    _d("2012-fy-df", 2012, "fy", "df", "2012/demonstracoes-financeiras-de-2012"),
    _d("2012-fy-audit", 2012, "fy", "audit", "2012/parecer-auditoria-independente-2012"),
    # ---- 2011 ----
    _d("2011-fy-df", 2011, "fy", "df", "2011/demonstracoes-financeiras-de-2011"),
    _d("2011-fy-audit", 2011, "fy", "audit", "2011/parecer-auditoria-independente-2011"),
    # ---- 2010 ----
    _d("2010-fy-df", 2010, "fy", "df", "2010/demonstracoes-financeiras-de-2010"),
    _d("2010-fy-audit", 2010, "fy", "audit", "2010/parecer-auditoria-independente-2010"),
    # ---- 2009 ----
    _d("2009-fy-df", 2009, "fy", "df", "2009/demonstracoes-financeiras-de-2009"),
    _d("2009-fy-audit", 2009, "fy", "audit", "2009/parecer-auditoria-independente-2009"),
    # ---- 2008 ----
    _d("2008-fy-df", 2008, "fy", "df", "2008/demonstracoes-financeiras-de-2008"),
    _d("2008-fy-audit", 2008, "fy", "audit", "2008/parecer-auditoria-independente-2008"),
    # ---- 2007 ----
    _d("2007-fy-df", 2007, "fy", "df", "2007/demonstracoes-financeiras-de-2007"),
    _d("2007-fy-audit", 2007, "fy", "audit", "2007/parecer-auditoria-independente-2007"),
    # ---- 2006 ----
    _d("2006-fy-df", 2006, "fy", "df", "2006/demonstracoes-financeiras-de-2006"),
    _d("2006-fy-audit", 2006, "fy", "audit", "2006/parecer-auditoria-independente-2006"),
    # ---- 2005 ----
    _d("2005-fy-df", 2005, "fy", "df", "2005/demonstracoes-financeiras-de-2005"),
    # ---- 2004 ----
    _d("2004-fy-df", 2004, "fy", "df", "2004/demonstracoes-financeiras-de-2004"),
    # ---- 2003 ----
    _d("2003-fy-df", 2003, "fy", "df", "2003/demonstracoes-financeiras-de-2003"),
    # ---- 2002 ----
    _d("2002-fy-df", 2002, "fy", "df", "2002/demonstracoes-financeiras-de-2002"),
    _d("2002-fy-audit", 2002, "fy", "audit", "2002/relatorio_auditoria_independente-2002.pdf"),
    # ---- 2001 ----
    _d("2001-fy-df", 2001, "fy", "df", "2001/demonstracoes_contabeis-2001.pdf"),
    _d("2001-fy-audit", 2001, "fy", "audit", "2001/relatorio_auditoria_independente-2001.pdf"),
)


def by_id(doc_id: str) -> Doc:
    for d in DOCS:
        if d.doc_id == doc_id:
            return d
    raise KeyError(doc_id)


def filter_docs(
    *,
    year: int | None = None,
    period: Period | None = None,
    kind: Kind | None = None,
    lang: Lang = "pt",
) -> list[Doc]:
    out = []
    for d in DOCS:
        if year is not None and d.year != year:
            continue
        if period is not None and d.period != period:
            continue
        if kind is not None and d.kind != kind:
            continue
        if d.lang != lang:
            continue
        out.append(d)
    return out


if __name__ == "__main__":
    import collections

    by_kind = collections.Counter(d.kind for d in DOCS)
    by_year = collections.Counter(d.year for d in DOCS)
    print(f"Total docs: {len(DOCS)}")
    print(f"By kind: {dict(by_kind)}")
    print(f"Year range: {min(by_year)}-{max(by_year)}")
    print(f"Years missing CF (Conselho Fiscal): "
          f"{sorted(set(range(2001, 2025)) - {d.year for d in DOCS if d.kind == 'cf'})}")
