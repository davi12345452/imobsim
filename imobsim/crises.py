"""Stress test com crises imobiliárias históricas.

Cada `Episodio` é uma trajetória macro (observada do SGS ou estilizada de
fontes públicas) mais uma lista de `Choque` na praça e no arquétipo, e um
mapeamento explícito de qual mecanismo da crise real corresponde a qual
parâmetro do modelo. A pergunta que o stress responde não é "o modelo prevê
a crise?" e sim: **esta praça e este arquétipo sobreviveriam àquele
caminho?**

Encaixe (quão bem o mecanismo da crise cabe no modelo):
    forte   venda na planta financiando obra, com caixa único ou por projeto
            (Encol, Brasil 2014-17, Espanha 2008, China 2021)
    fraco   a quebra foi em outro lugar (EUA 2008: crédito ao comprador,
            securitização e mercado secundário, que o modelo não tem)

Os choques são estilizações grosseiras de séries públicas (PNAD, Abrainc,
INE, NBS, BLS). Estão aqui para dar ordem de grandeza, não para reproduzir
o episódio.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import macro as _macro
from .incorporadora import ARQUETIPOS
from .praca import PRACAS
from .sim import Choque, resumo, run


@dataclass
class Episodio:
    nome: str
    titulo: str
    inicio: str                     # YYYY-MM
    meses: int
    macro: str | Callable[[int], pd.DataFrame]
    choques: list[Choque] = field(default_factory=list)
    mecanismo: dict[str, str] = field(default_factory=dict)  # crise real -> parâmetro
    encaixe: str = "forte"
    resumo: str = ""
    fontes: list[str] = field(default_factory=list)

    def cenario(self):
        return _macro.cenario(self.macro)


def _estilizado(nome: str, inicio: str, n: int, juros: dict[int, float],
                fin: dict[int, float], custo: dict[int, float]) -> pd.DataFrame:
    """Macro estilizado por interpolação de pontos {mes: valor}."""
    idx = pd.period_range(inicio, periods=n, freq="M")
    df = pd.DataFrame(index=idx)
    df["selic"] = _macro._interp(juros, n)
    df["cdi"] = df["selic"]
    df["taxa_fin"] = _macro._interp(fin, n)
    df["incc_aa"] = _macro._interp(custo, n)
    df["incc_mm"] = (1 + df["incc_aa"] / 100) ** (1 / 12) - 1
    df.attrs["nome"] = nome
    return df


def _encol_macro(n: int) -> pd.DataFrame:
    """Selic e INCC observados (SGS); taxa de financiamento fixada em 15%
    (SFH com teto de 12% + TR; na prática o comprador autofinanciava a obra)."""
    df = _macro.historico("1995-07", n)
    df["taxa_fin"] = 15.0
    df.attrs["nome"] = "encol_1995_99"
    return df


EPISODIOS: dict[str, Episodio] = {}


def _reg(ep: Episodio) -> Episodio:
    EPISODIOS[ep.nome] = ep
    return ep


_reg(Episodio(
    nome="encol_1995_99",
    titulo="Encol (Brasil, 1995–99)",
    inicio="1995-07", meses=48,
    macro=_encol_macro,
    choques=[
        Choque(24, "praca", "demanda_base_mensal", 0.85,
               nota="crise asiática (out/1997): crédito seca, Selic vai a 43%"),
        Choque(38, "praca", "confianca", 0.85, nota="crise russa (set/1998), Selic a 40%"),
        Choque(30, "arquetipo", "limite_credito", 0.5,
               nota="bancos cortam linha da construtora após a concordata (nov/1997)"),
    ],
    mecanismo={
        "caixa único entre ~700 obras, recebível de uma pagando a outra": "afetacao=False",
        "comprador autofinanciava a obra (sem SFH efetivo)": "entrada+obra = 40% do preço",
        "Selic de 25–45% encarece plano empresário e dívida corporativa": "cdi observado",
        "resultado: 42 mil compradores sem imóvel; Lei 10.931/2004": "afetacao=True",
    },
    encaixe="forte",
    resumo="O caso que deu origem ao patrimônio de afetação. Obra de hoje paga com "
           "lançamento de agora, em escala nacional, com Selic de dois dígitos altos.",
    fontes=["SGS 4189 e 192", "Lei 10.931/2004 (patrimônio de afetação)",
            "Encol: concordata nov/1997, falência mar/1999"],
))

_reg(Episodio(
    nome="brasil_2014_17",
    titulo="Brasil (2014–17)",
    inicio="2014-01", meses=48,
    macro="historico:2014-01",
    choques=[
        Choque(12, "praca", "renda_comprador", 0.96, nota="renda real cai ~4% em 2015"),
        Choque(15, "praca", "confianca", 0.85, nota="recessão + Lava Jato (2T2015)"),
        Choque(16, "praca", "entrada_pct", 1.5,
               nota="Caixa reduz LTV e raciona SBPE (mai/2015): entrada 20% -> 30%"),
        Choque(18, "praca", "demanda_base_mensal", 0.8,
               nota="desemprego de 6,8% para 13,7% (PNAD, 2014 -> 1T2017)"),
        Choque(24, "praca", "renda_comprador", 0.96, nota="renda real cai de novo em 2016"),
    ],
    mecanismo={
        "Selic 14,25% por 15 meses, SBPE de 9% a 11%": "historico:2014-01",
        "distratos de ~40% das vendas brutas em 2016 (Abrainc/Fipe)": "repasse falha -> distrato",
        "racionamento de crédito da Caixa": "entrada_pct x 1,5",
        "PDG, Viver, Rossi em recuperação judicial (2016–17)": "fluxo_dependente quebra",
    },
    encaixe="forte",
    resumo="O único episódio com dados de saída para conferir: timing das RJs, onda de "
           "distratos e queda de lançamentos.",
    fontes=["SGS 4189, 192, 20774", "Abrainc/Fipe: distratos 2016", "PNAD Contínua"],
))

_reg(Episodio(
    nome="espanha_2007_12",
    titulo="Espanha (2007–12)",
    inicio="2007-07", meses=60,
    macro=lambda n: _estilizado(
        "espanha_2007_12", "2007-07", n,
        juros={0: 4.5, 15: 5.4, 24: 1.6, 36: 1.4, 48: 2.2, 59: 1.0},   # Euribor 12m
        fin={0: 5.5, 15: 6.4, 24: 2.8, 36: 2.6, 48: 3.4, 59: 2.6},     # hipoteca ~ Euribor + 1
        custo={0: 4.0, 12: 3.0, 24: 0.5, 59: 0.5},
    ),
    choques=[
        Choque(12, "praca", "demanda_base_mensal", 0.5,
               nota="compras de imóvel novo caem ~50% em 2008 (INE)"),
        Choque(12, "praca", "entrada_pct", 1.75,
               nota="fim das hipotecas a 100%: entrada 20% -> 35%"),
        Choque(14, "praca", "confianca", 0.7, nota="Lehman (set/2008)"),
        Choque(14, "arquetipo", "limite_credito", 0.3,
               nota="bancos fecham crédito às promotoras; Martinsa-Fadesa em concurso (jul/2008)"),
        Choque(18, "praca", "renda_comprador", 0.85, nota="desemprego de 8% para 20% (2010)"),
        Choque(30, "praca", "renda_comprador", 0.9, nota="desemprego a 26% (2013)"),
    ],
    mecanismo={
        "promotoras financiadas por pré-venda + crédito bancário": "fluxo_dependente",
        "juros CAEM e a demanda desaba mesmo assim": "renda x demanda x entrada, não taxa_fin",
        "estoque de ~650 mil unidades novas sem vender": "meses de estoque explodem",
        "crédito bancário às promotoras seca": "limite_credito x 0,3",
    },
    encaixe="forte",
    resumo="Mecanismo quase idêntico ao fluxo_dependente. Mostra que taxa cair não salva "
           "ninguém quando renda e crédito somem juntos.",
    fontes=["Euribor 12m (BCE)", "INE: transacciones de vivienda", "Ministerio de Fomento: stock"],
))

_reg(Episodio(
    nome="china_2021_23",
    titulo="China / Evergrande (2021–23)",
    inicio="2021-01", meses=36,
    macro=lambda n: _estilizado(
        "china_2021_23", "2021-01", n,
        juros={0: 4.65, 12: 4.65, 20: 4.3, 35: 4.2},      # LPR 5 anos
        fin={0: 5.6, 12: 5.6, 20: 4.3, 35: 4.0},          # hipoteca média
        custo={0: 3.0, 12: 2.0, 35: 1.0},
    ),
    choques=[
        Choque(8, "arquetipo", "limite_credito", 0.0,
               nota="'três linhas vermelhas' + default da Evergrande (set/2021): linha fecha"),
        Choque(8, "praca", "confianca", 0.7, nota="medo de não receber o imóvel"),
        Choque(12, "praca", "demanda_base_mensal", 0.6,
               nota="vendas de imóveis novos caem ~30–40% em 2022 (NBS)"),
        Choque(18, "praca", "confianca", 0.85, nota="boicote de hipotecas (jul/2022)"),
    ],
    mecanismo={
        "pré-venda financiando obra de OUTRO projeto, caixa único": "afetacao=False",
        "governo aperta escrow por projeto": "afetacao=True (o remédio é o mesmo do Brasil)",
        "insolvência com caixa consolidado positivo preso em projetos":
            "caixa_total > 0 e insolvente",
        "crédito fecha por regra, não por juros": "limite_credito x 0",
    },
    encaixe="forte",
    resumo="Juros caem, crédito fecha por regulação e o comprador para de confiar na entrega. "
           "É a versão em escala continental do 'obra paga com lançamento'.",
    fontes=["NBS: vendas de imóveis novos", "PBoC: LPR 5y", "Evergrande default set/dez 2021"],
))

_reg(Episodio(
    nome="eua_2006_10",
    titulo="EUA / subprime (2006–10)",
    inicio="2006-07", meses=48,
    macro=lambda n: _estilizado(
        "eua_2006_10", "2006-07", n,
        juros={0: 5.25, 14: 4.25, 20: 2.0, 29: 0.25, 47: 0.25},    # Fed funds
        fin={0: 6.7, 14: 6.3, 26: 6.0, 36: 5.0, 47: 4.7},         # 30y fixed
        custo={0: 5.0, 18: 3.0, 30: -2.0, 47: 0.0},
    ),
    choques=[
        Choque(12, "praca", "confianca", 0.85, nota="subprime estoura (jul–ago/2007)"),
        Choque(14, "praca", "entrada_pct", 1.5, nota="fim do zero-down: entrada 20% -> 30%"),
        Choque(26, "praca", "confianca", 0.7, nota="Lehman (set/2008)"),
        Choque(26, "praca", "demanda_base_mensal", 0.6, nota="vendas de casas novas -40%"),
        Choque(26, "arquetipo", "limite_credito", 0.3, nota="crédito a construtoras seca"),
        Choque(30, "praca", "renda_comprador", 0.95, nota="desemprego a 10% (2009)"),
    ],
    mecanismo={
        "quebra no crédito ao comprador e na securitização": "SEM equivalente no modelo",
        "mercado secundário arrasta o preço do novo": "SEM equivalente (não há secundário)",
        "construtoras (homebuilders) quebram por estoque + dívida":
            "demanda x 0,6, limite_credito x 0,3",
    },
    encaixe="fraco",
    resumo="Incluído para contraste. O modelo só captura a ponta da construtora; a "
           "mecânica central da crise (MBS, secundário) não existe aqui.",
    fontes=["FRED: FEDFUNDS, MORTGAGE30US", "Census: new home sales", "Case-Shiller"],
))


# ---------------------------------------------------------------------------

def episodio(spec: str | Episodio) -> Episodio:
    if isinstance(spec, Episodio):
        return spec
    try:
        return EPISODIOS[spec]
    except KeyError:
        raise KeyError(f"episódio desconhecido: {spec!r}. Use um de {list(EPISODIOS)}") from None


def stress(nome_arq: str, nome_praca, ep: str | Episodio, meses: int | None = None,
           com_choques: bool = True) -> pd.DataFrame:
    """Roda `nome_arq` em `nome_praca` sob o episódio. `com_choques=False` isola
    o efeito do caminho macro puro."""
    ep = episodio(ep)
    n = meses or ep.meses
    df = run(ep.cenario(), nome_praca, nome_arq, meses=n,
             choques=ep.choques if com_choques else ())
    df.attrs.update(episodio=ep.nome, macro=ep.nome)
    return df


def grade_stress(episodios: Iterable[str | Episodio] | None = None,
                 pracas: Iterable | None = None,
                 arqs: Iterable[str] | None = None,
                 com_choques: bool = True) -> dict[tuple, pd.DataFrame]:
    eps = [episodio(e) for e in (episodios or EPISODIOS.values())]
    pracas = list(pracas) if pracas else list(PRACAS)
    arqs = list(arqs) if arqs else list(ARQUETIPOS)
    return {(ep.nome, p, a): stress(a, p, ep, com_choques=com_choques)
            for ep in eps for p in pracas for a in arqs}


def resumo_stress(res: dict[tuple, pd.DataFrame]) -> pd.DataFrame:
    """`resumo` mais o mês relativo da quebra e o encaixe do episódio."""
    tab = resumo(res).rename(columns={"macro": "episodio"})
    tab["quebra_em_meses"] = [
        df.attrs["insolvente_em"] if df.attrs["insolvente_em"] is not None else np.nan
        for df in res.values()
    ]
    tab["encaixe"] = [EPISODIOS[e].encaixe for e in tab["episodio"]]
    cols = ["episodio", "praca", "arquetipo", "insolvente_em", "quebra_em_meses", "encaixe"]
    return tab[cols + [c for c in tab.columns if c not in cols]]
