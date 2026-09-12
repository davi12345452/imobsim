"""Loop de simulação, grade de cenários e fronteiras.

Uma rodada (`run`) combina um cenário macro, uma praça e um arquétipo de
incorporadora e devolve um DataFrame mensal com o estado dos três.
`grade` roda o produto cartesiano; `resumo` condensa cada rodada em uma
linha. `vso_minima` e `crescimento_minimo` varrem um parâmetro do arquétipo
e devolvem o menor valor com o qual ele sobrevive ao horizonte.
"""
from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .incorporadora import ARQUETIPOS, Incorporadora
from .macro import CENARIOS, cenario
from .praca import PRACAS


def _monta(nome_macro, nome_praca: str, nome_arq: str, meses: int):
    macro = cenario(nome_macro)(meses)
    praca = PRACAS[nome_praca]()
    arq = ARQUETIPOS[nome_arq](praca.preco * praca.metragem_media)
    return macro, praca, arq


@dataclass(frozen=True)
class Choque:
    """Intervenção exógena em um mês da simulação.

    Multiplica (ou fixa, se `valor` for dado) um atributo da praça ou do
    arquétipo. É como os episódios de crise entram no modelo: recessão é
    `renda_comprador` x 0.95, restrição de crédito é `entrada_pct` x 1.5,
    fechamento da linha bancária é `limite_credito` x 0, e assim por diante.
    """
    mes: int
    alvo: str          # "praca" | "arquetipo"
    campo: str
    fator: float = 1.0
    valor: float | None = None
    nota: str = ""

    def aplicar(self, praca, arq):
        obj = {"praca": praca, "arquetipo": arq}[self.alvo]
        atual = getattr(obj, self.campo)
        setattr(obj, self.campo, self.valor if self.valor is not None else atual * self.fator)


def _aplicar_choques(choques, t, praca, arq):
    for c in choques:
        if c.mes == t:
            c.aplicar(praca, arq)


def _vso_praca(praca, macro_t) -> tuple[float, float]:
    """VSO da praça com o estoque do início do mês (antes da construtora agir)."""
    dem, sa = praca.demanda(macro_t)
    vso = min(dem, praca.estoque) / praca.estoque if praca.estoque > 0 else 0.0
    return vso, sa


def run(nome_macro, nome_praca: str, nome_arq: str, meses: int = 48,
        choque_confianca_quebra: float = 0.25,
        choques: Iterable[Choque] = ()) -> pd.DataFrame:
    """Simula uma combinação (macro, praça, arquétipo) por `meses` meses.

    `nome_macro` aceita tudo que `macro.cenario` aceita: "focus_base",
    "historico:2014-01", "focus:2026-09-04", um callable ou um DataFrame.
    `choques` são intervenções exógenas (ver `Choque`) aplicadas no início do
    mês indicado, antes de a praça calcular a demanda.

    Quando a construtora quebra, a praça recebe um choque único de confiança
    (`choque_confianca_quebra`): obra parada na cidade afeta a demanda de todos.
    O mês da insolvência (ou None) fica em `df.attrs["insolvente_em"]`.
    """
    macro, praca, arq = _monta(nome_macro, nome_praca, nome_arq, meses)
    inc = Incorporadora(arq, praca)

    linhas = []
    choque_aplicado = False
    choques = list(choques)
    for t in range(meses):
        m = macro.iloc[t]
        _aplicar_choques(choques, t, praca, arq)
        vso, sa = _vso_praca(praca, m)
        r_inc = inc.step(t, m, vso, sa, praca)
        choque = 0.0
        if r_inc["insolvente"] and not choque_aplicado:
            choque = choque_confianca_quebra
            choque_aplicado = True
        r_pr = praca.step(m, r_inc["lancamentos"], choque)
        linhas.append({"t": t, "mes": str(macro.index[t]), **m.to_dict(),
                       **{f"praca_{k}": v for k, v in r_pr.items()},
                       **{f"inc_{k}": v for k, v in r_inc.items()}})
    df = pd.DataFrame(linhas)
    df.attrs.update(macro=macro.attrs.get("nome", str(nome_macro)), praca=nome_praca,
                    arq=nome_arq, insolvente_em=inc.insolvente_em)
    return df


def grade(meses: int = 48, macros: Iterable | None = None,
          pracas: Iterable[str] | None = None,
          arqs: Iterable[str] | None = None) -> dict[tuple, pd.DataFrame]:
    """Roda todas as combinações de macro x praça x arquétipo.

    `macros` aceita especificações de `macro.cenario` (strings, callables)."""
    macros = list(macros) if macros else list(CENARIOS)
    pracas = list(pracas) if pracas else list(PRACAS)
    arqs = list(arqs) if arqs else list(ARQUETIPOS)
    return {(m, p, a): run(m, p, a, meses)
            for m, p, a in itertools.product(macros, pracas, arqs)}


def resumo(res: dict[tuple, pd.DataFrame]) -> pd.DataFrame:
    """Uma linha por rodada: mês da quebra, caixa mínimo/final, preço, estoque, VSO."""
    rows = []
    for (m, p, a), df in res.items():
        ins = df.attrs["insolvente_em"]
        rows.append(dict(
            macro=m, praca=p, arquetipo=a,
            insolvente_em=df["mes"].iloc[ins] if ins is not None else "sobrevive",
            caixa_min_MM=df["inc_caixa_liquido"].min() / 1e6,
            caixa_final_MM=df["inc_caixa_liquido"].iloc[-1] / 1e6,
            lancamentos=int(df["inc_lancamentos"].gt(0).sum()),
            preco_var_pct=(df["praca_preco_m2"].iloc[-1] / df["praca_preco_m2"].iloc[0] - 1) * 100,
            estoque_meses_fim=df["praca_meses_estoque"].iloc[-12:].mean(),
            vso_medio_pct=df["praca_vso"].mean() * 100,
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fronteiras: varre um parâmetro do arquétipo e acha o menor valor que sobrevive
# ---------------------------------------------------------------------------

def _fronteira(param: str, grid: np.ndarray, nome_macro, nome_praca: str,
               nome_arq: str, meses: int) -> dict:
    """Para cada valor de `grid`, seta `arq.<param>` e devolve o mês da insolvência
    (None = sobreviveu). Sem choque de confiança: a fronteira é da construtora
    isolada, não da praça reagindo à quebra."""
    detalhe: dict[float, int | None] = {}
    for g in grid:
        macro, praca, arq = _monta(nome_macro, nome_praca, nome_arq, meses)
        setattr(arq, param, float(g))
        inc = Incorporadora(arq, praca)
        ins = None
        for t in range(meses):
            m = macro.iloc[t]
            vso, sa = _vso_praca(praca, m)
            r = inc.step(t, m, vso, sa, praca)
            praca.step(m, r["lancamentos"], 0.0)
            if r["insolvente"]:
                ins = t
                break
        detalhe[float(g)] = ins
    sobrevive = [g for g, i in detalhe.items() if i is None]
    return dict(minimo=min(sobrevive) if sobrevive else None, detalhe=detalhe)


def vso_minima(nome_macro, nome_praca: str, nome_arq: str = "fluxo_dependente",
               meses: int = 48, grid=None) -> dict:
    """Menor velocidade de vendas relativa à praça (`fator_vendas`) com a qual a
    construtora sobrevive o horizonte. Responde: quanto acima do mercado a
    equipe comercial precisa vender para o fluxo fechar."""
    grid = grid if grid is not None else np.round(np.arange(0.8, 3.01, 0.1), 2)
    return _fronteira("fator_vendas", grid, nome_macro, nome_praca, nome_arq, meses)


def crescimento_minimo(nome_macro, nome_praca: str, nome_arq: str = "fluxo_dependente",
                       meses: int = 48, grid=None) -> dict:
    """Menor fator de crescimento de lançamentos (`crescimento_lanc`) com o qual
    a construtora sobrevive o horizonte: quanto o próximo lançamento precisa
    ser maior que o anterior só para manter o caixa."""
    grid = grid if grid is not None else np.round(np.arange(0.8, 2.01, 0.05), 2)
    return _fronteira("crescimento_lanc", grid, nome_macro, nome_praca, nome_arq, meses)
