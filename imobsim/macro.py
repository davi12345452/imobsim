"""Cenários macroeconômicos exógenos.

Cada cenário é um DataFrame mensal. O restante do modelo apenas LÊ estas
séries; nada aqui depende da praça ou da construtora.

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


def _monta(nome: str, selic: np.ndarray, incc_aa: np.ndarray, n: int) -> pd.DataFrame:
    idx = pd.period_range("2026-09", periods=n, freq="M")
    df = pd.DataFrame(index=idx)
    df["selic"] = selic
    df["cdi"] = selic
    # SBPE historicamente roda ~ 5 + 0.55*Selic (14.5 -> ~13; 10 -> ~10.5)
    df["taxa_fin"] = 5.0 + 0.55 * selic
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
