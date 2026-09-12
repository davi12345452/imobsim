"""Monte Carlo sobre as premissas mais incertas.

Quatro fontes de ruído, independentes entre si:
    selic     passeio aleatório somado ao caminho base; desvio em 12 meses =
              `sigma_selic_12m` (default: desvio-padrão do Focus para o ano seguinte)
    incc      idem, sobre o INCC anual; `sigma_incc_12m` (default: desvio do
              Focus para o IPCA, x1.5 porque INCC é mais volátil)
    degrau    `degrau_inicial` x lognormal(0, sigma_degrau)
    demanda   `demanda_base_mensal` x lognormal(0, sigma_demanda)

taxa_fin acompanha a Selic sorteada (0.55 p.p. por p.p.), CDI = Selic.
O arquétipo não é sorteado: a pergunta é "dado este balanço, qual a chance
de o mundo quebrá-lo", não "qual balanço sorteado quebra".
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .incorporadora import ARQUETIPOS, Incorporadora
from .macro import cenario
from .praca import praca as _praca
from .sim import _vso_praca


@dataclass(frozen=True)
class Sigmas:
    selic_12m: float = 1.0      # p.p. de Selic a 12 meses
    incc_12m: float = 1.0       # p.p. de INCC anual a 12 meses
    degrau: float = 0.30        # log-desvio do degrau inicial
    demanda: float = 0.15       # log-desvio da demanda base


def sigmas_do_focus(data: str, mult_incc: float = 1.5, **kw) -> Sigmas:
    """Dispersão de Selic e IPCA do Focus (ano seguinte ao de `data`) como sigma."""
    from . import fontes

    ano = pd.Timestamp(data).year + 1
    selic = fontes.focus(data, "Selic")
    ipca = fontes.focus(data, "IPCA")
    s_sel = float(selic.loc[selic["ano"] == ano, "desvio"].iloc[0])
    s_ipc = float(ipca.loc[ipca["ano"] == ano, "desvio"].iloc[0])
    return Sigmas(selic_12m=s_sel, incc_12m=mult_incc * s_ipc, **kw)


def _passeio(rng: np.random.Generator, n: int, sigma_12m: float) -> np.ndarray:
    if sigma_12m <= 0:
        return np.zeros(n)
    passos = rng.normal(0.0, sigma_12m / np.sqrt(12), n)
    passos[0] = 0.0
    return np.cumsum(passos)


def amostrar_macro(base: pd.DataFrame, rng: np.random.Generator, sig: Sigmas) -> pd.DataFrame:
    """Uma trajetória macro sorteada em torno de `base`."""
    n = len(base)
    df = base.copy()
    e_sel = _passeio(rng, n, sig.selic_12m)
    e_inc = _passeio(rng, n, sig.incc_12m)
    df["selic"] = np.maximum(base["selic"].to_numpy() + e_sel, 2.0)
    df["cdi"] = df["selic"]
    df["taxa_fin"] = base["taxa_fin"].to_numpy() + 0.55 * (df["selic"] - base["selic"])
    df["incc_aa"] = np.maximum(base["incc_aa"].to_numpy() + e_inc, -2.0)
    df["incc_mm"] = (1 + df["incc_aa"] / 100) ** (1 / 12) - 1
    return df


def monte_carlo(nome_macro, nome_praca, nome_arq: str, n: int = 200, seed: int = 0,
                meses: int = 48, sigmas: Sigmas | None = None) -> pd.DataFrame:
    """`n` rodadas com macro, degrau e demanda sorteados. Uma linha por rodada:
    insolvente_em (mês ou NaN), caixa_min_MM, caixa_final_MM e os fatores
    sorteados, para análise de sensibilidade. `attrs["prob_quebra"]`."""
    sig = sigmas or Sigmas()
    rng = np.random.default_rng(seed)
    base = cenario(nome_macro)(meses)
    fab = _praca(nome_praca)
    linhas = []
    for i in range(n):
        macro = amostrar_macro(base, rng, sig)
        f_deg = float(np.exp(rng.normal(0, sig.degrau))) if sig.degrau > 0 else 1.0
        f_dem = float(np.exp(rng.normal(0, sig.demanda))) if sig.demanda > 0 else 1.0
        p0 = fab()
        praca = replace(p0, degrau_inicial=p0.degrau_inicial * f_deg,
                        demanda_base_mensal=p0.demanda_base_mensal * f_dem)
        arq = ARQUETIPOS[nome_arq](praca.preco * praca.metragem_media)
        inc = Incorporadora(arq, praca)
        caixa = []
        ins = None
        for t in range(meses):
            m = macro.iloc[t]
            vso, sa = _vso_praca(praca, m)
            r = inc.step(t, m, vso, sa, praca)
            praca.step(m, r["lancamentos"], 0.0)
            caixa.append(r["caixa_liquido"])
            if r["insolvente"] and ins is None:
                ins = t
        linhas.append(dict(
            amostra=i, insolvente_em=ins if ins is not None else np.nan,
            caixa_min_MM=min(caixa) / 1e6, caixa_final_MM=caixa[-1] / 1e6,
            selic_media=float(macro["selic"].mean()),
            selic_desvio_base=float((macro["selic"] - base["selic"]).mean()),
            incc_medio=float(macro["incc_aa"].mean()),
            fator_degrau=f_deg, fator_demanda=f_dem,
        ))
    df = pd.DataFrame(linhas)
    df.attrs.update(macro=base.attrs.get("nome", str(nome_macro)), praca=praca.nome,
                    arq=nome_arq, n=n, seed=seed, sigmas=sig,
                    prob_quebra=float(df["insolvente_em"].notna().mean()))
    return df


def resumo_mc(df: pd.DataFrame) -> dict:
    """Probabilidade de quebra, quantis do mês e sensibilidade (Spearman) do
    resultado a cada fator sorteado."""
    quebrou = df["insolvente_em"].notna()
    alvo = df["insolvente_em"].fillna(df["insolvente_em"].max() + 12 if quebrou.any() else 0)
    fatores = ["selic_desvio_base", "incc_medio", "fator_degrau", "fator_demanda"]
    # Spearman = Pearson dos postos (sem depender de scipy)
    sens = {f: float(alvo.rank().corr(df[f].rank())) if alvo.nunique() > 1 else 0.0
            for f in fatores}
    q = df.loc[quebrou, "insolvente_em"].quantile([0.1, 0.5, 0.9]) if quebrou.any() else None
    return dict(
        macro=df.attrs["macro"], praca=df.attrs["praca"], arquetipo=df.attrs["arq"],
        n=df.attrs["n"], prob_quebra=df.attrs["prob_quebra"],
        mes_quebra_p10=float(q.iloc[0]) if q is not None else np.nan,
        mes_quebra_p50=float(q.iloc[1]) if q is not None else np.nan,
        mes_quebra_p90=float(q.iloc[2]) if q is not None else np.nan,
        caixa_min_p10_MM=float(df["caixa_min_MM"].quantile(0.1)),
        caixa_min_p50_MM=float(df["caixa_min_MM"].quantile(0.5)),
        **{f"sens_{k}": v for k, v in sens.items()},
    )


def grade_mc(nome_macro="focus_base", pracas=None, arqs=None, n: int = 200, seed: int = 0,
             meses: int = 48, sigmas: Sigmas | None = None) -> dict[tuple, pd.DataFrame]:
    from .incorporadora import ARQUETIPOS as A
    from .praca import PRACAS as P
    pracas = list(pracas) if pracas else list(P)
    arqs = list(arqs) if arqs else list(A)
    return {(p, a): monte_carlo(nome_macro, p, a, n=n, seed=seed + 97 * k, meses=meses,
                                sigmas=sigmas)
            for k, (p, a) in enumerate((p, a) for p in pracas for a in arqs)}
