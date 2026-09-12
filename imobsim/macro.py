"""Cenários macroeconômicos exógenos.

Cada cenário é um DataFrame mensal. O restante do modelo apenas LÊ estas
séries; nada aqui depende da praça ou da construtora.

Três famílias de cenário:
    estilizados   focus_base / fiscal_adverso / benigno (interpolação manual,
                  são os do estudo original e do README)
    historico     séries observadas do SGS a partir de um mês qualquer
                  ("historico:2014-01")
    focus         mediana Focus na data pedida, ancorada na Selic e na taxa
                  SBPE observadas naquele mês ("focus:2026-09-04")

`cenario(spec)` resolve qualquer uma das três a partir de uma string.

Colunas:
    selic       taxa anual (%)
    cdi         taxa anual (%), ~ selic
    taxa_fin    taxa anual do financiamento SBPE ao comprador (%)
    incc_aa     INCC anualizado (%)
    incc_mm     INCC mensal (fração)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MESES_PADRAO = 48  # set/2026 -> ago/2030


def _interp(pontos: dict[int, float], n: int) -> np.ndarray:
    """Interpola linearmente valores anuais em {mes: valor} para n meses."""
    xs = sorted(pontos)
    ys = [pontos[x] for x in xs]
    return np.interp(np.arange(n), xs, ys)


INICIO_PADRAO = "2026-09"


def taxa_sbpe_regra(selic: np.ndarray) -> np.ndarray:
    """SBPE historicamente roda ~ 5 + 0.55*Selic (14.5 -> ~13; 10 -> ~10.5)."""
    return 5.0 + 0.55 * selic


def _monta(nome: str, selic: np.ndarray, incc_aa: np.ndarray, n: int,
           inicio: str = INICIO_PADRAO, taxa_fin: np.ndarray | None = None) -> pd.DataFrame:
    idx = pd.period_range(inicio, periods=n, freq="M")
    df = pd.DataFrame(index=idx)
    df["selic"] = selic
    df["cdi"] = selic
    df["taxa_fin"] = taxa_sbpe_regra(selic) if taxa_fin is None else taxa_fin
    df["incc_aa"] = incc_aa
    df["incc_mm"] = (1 + incc_aa / 100) ** (1 / 12) - 1
    df.attrs["nome"] = nome
    return df


def focus_base(n: int = MESES_PADRAO) -> pd.DataFrame:
    """Mediana Focus set/2026: 13,75 fim-26, 12,0 fim-27, 10,5 fim-28, 10,0 fim-29."""
    selic = _interp({0: 14.25, 3: 13.75, 15: 12.0, 27: 10.5, 39: 10.0, n - 1: 10.0}, n)
    incc = _interp({0: 6.5, 15: 6.0, n - 1: 5.0}, n)
    return _monta("focus_base", selic, incc, n)


def fiscal_adverso(n: int = MESES_PADRAO) -> pd.DataFrame:
    """Choque fiscal pós-eleição: Selic volta a subir no 1º sem/2027 e fica alta."""
    selic = _interp({0: 14.25, 3: 14.0, 9: 15.5, 21: 15.5, 33: 14.0, n - 1: 13.0}, n)
    incc = _interp({0: 6.5, 12: 9.0, 24: 8.0, n - 1: 7.0}, n)
    return _monta("fiscal_adverso", selic, incc, n)


def benigno(n: int = MESES_PADRAO) -> pd.DataFrame:
    """Ajuste fiscal crível: corte acelerado, Selic ~11 fim-27, 9 fim-28."""
    selic = _interp({0: 14.25, 3: 13.5, 15: 11.0, 27: 9.0, n - 1: 8.5}, n)
    incc = _interp({0: 6.5, 12: 5.0, n - 1: 4.5}, n)
    return _monta("benigno", selic, incc, n)


CENARIOS = {
    "focus_base": focus_base,
    "fiscal_adverso": fiscal_adverso,
    "benigno": benigno,
}


# ---------------------------------------------------------------------------
# Cenários a partir de dados (SGS / Focus)
# ---------------------------------------------------------------------------

def historico(inicio: str, n: int = MESES_PADRAO, estender: bool = False) -> pd.DataFrame:
    """Séries observadas do SGS a partir de `inicio` (YYYY-MM) por `n` meses.

    taxa_fin usa a taxa média SBPE regulada (SGS 20774) quando existe
    (mar/2011 em diante) e a regra 5 + 0.55*Selic antes disso. INCC anual é o
    acumulado dos 12 meses anteriores. Se o horizonte passa do último mês
    observado, levanta erro, a menos que `estender=True` (repete o último
    valor)."""
    from . import fontes

    base = fontes.sgs()
    ini = pd.Period(inicio, "M")
    fim = ini + n - 1
    if fim > base.index[-1]:
        if not estender:
            raise ValueError(f"SGS vai até {base.index[-1]}; pedido até {fim}. "
                             "Use estender=True ou um horizonte menor.")
        extra = pd.period_range(base.index[-1] + 1, fim, freq="M")
        base = pd.concat([base, pd.DataFrame(index=extra, columns=base.columns)]).ffill()
    if ini < base.index[0]:
        raise ValueError(f"SGS começa em {base.index[0]}")
    incc_aa_full = ((1 + base["incc_mm"] / 100).rolling(12).apply(np.prod, raw=True) - 1) * 100
    jan = base.loc[ini:fim]
    selic = jan["selic"].to_numpy(float)
    taxa_fin = jan["taxa_fin"].to_numpy(float)
    regra = taxa_sbpe_regra(selic)
    taxa_fin = np.where(np.isnan(taxa_fin), regra, taxa_fin)
    incc_aa = incc_aa_full.loc[ini:fim].bfill().to_numpy(float)
    df = _monta(f"historico:{inicio}", selic, incc_aa, n, inicio=str(ini), taxa_fin=taxa_fin)
    # substitui o INCC mensal derivado do anual pelo observado
    df["incc_mm"] = jan["incc_mm"].to_numpy(float) / 100
    return df


def focus(data: str, n: int = MESES_PADRAO, incc_spread: float = 1.5) -> pd.DataFrame:
    """Mediana Focus (Selic e IPCA por ano-calendário) na última divulgação
    <= `data`, interpolada mensalmente a partir do observado no mês de `data`.

    - Selic parte da Selic mensal observada (SGS 4189) e passa pela mediana
      de dezembro de cada ano; depois do último ano, fica constante.
    - INCC parte do acumulado observado em 12 meses (SGS 192) e converge
      para IPCA Focus + `incc_spread` p.p. (o Focus não projeta INCC).
    - taxa_fin parte da última SBPE observada (SGS 20774) e move 0.55 p.p.
      por p.p. de Selic, em vez da regra absoluta, para não descolar do nível
      atual.
    """
    from . import fontes

    base = fontes.sgs()
    mes0 = pd.Period(pd.Timestamp(data), "M")
    obs = base.loc[:mes0].iloc[-1]
    inicio = str(mes0 + 1)  # projeta a partir do mês seguinte à divulgação
    idx = pd.period_range(inicio, periods=n, freq="M")

    def caminho(ind: str, v0: float) -> np.ndarray:
        f = fontes.focus(data, ind)
        pontos = {0: v0}
        for ano, med in zip(f["ano"], f["mediana"]):
            k = (pd.Period(f"{ano}-12", "M") - idx[0]).n
            if k >= 0:
                pontos[k] = float(med)
        pontos[n - 1] = pontos[max(pontos)]
        return _interp(pontos, n)

    selic = caminho("Selic", float(obs["selic"]))
    # INCC parte do acumulado observado em 12 meses e converge para IPCA Focus + spread
    incc_aa0 = ((1 + base.loc[:mes0, "incc_mm"].iloc[-12:] / 100).prod() - 1) * 100
    incc_aa = caminho("IPCA", float(incc_aa0) - incc_spread) + incc_spread
    # SBPE observada tem ~2 meses de defasagem: usa o último valor publicado
    sbpe_obs = base.loc[:mes0, "taxa_fin"].dropna()
    sbpe0 = float(sbpe_obs.iloc[-1]) if len(sbpe_obs) else taxa_sbpe_regra(selic[:1])[0]
    taxa_fin = sbpe0 + 0.55 * (selic - selic[0])
    return _monta(f"focus:{data}", selic, incc_aa, n, inicio=inicio, taxa_fin=taxa_fin)


def cenario(spec):
    """Resolve uma especificação de cenário para um callable(n) -> DataFrame.

    Aceita: nome em CENARIOS ("focus_base"), "historico:YYYY-MM",
    "focus:YYYY-MM-DD", um callable(n) ou um DataFrame já montado."""
    if callable(spec):
        return spec
    if isinstance(spec, pd.DataFrame):
        return lambda n: spec.iloc[:n]
    if spec in CENARIOS:
        return CENARIOS[spec]
    kind, _, arg = str(spec).partition(":")
    if kind == "historico" and arg:
        return lambda n: historico(arg, n)
    if kind == "focus" and arg:
        return lambda n: focus(arg, n)
    raise KeyError(f"cenário desconhecido: {spec!r}. Use um de {list(CENARIOS)}, "
                   "'historico:YYYY-MM' ou 'focus:YYYY-MM-DD'.")
