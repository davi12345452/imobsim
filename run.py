"""Roda a grade completa e gera resumo + gráficos.

    python run.py [--meses 48] [--out ./out] [--macros focus_base historico:2014-01 ...]

Sem `--macros`, usa os três cenários estilizados do estudo original.
"""
from __future__ import annotations

import argparse
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from imobsim import ARQUETIPOS, CENARIOS, PRACAS, grade, resumo, vso_minima

CORES_FIXAS = {"benigno": "#2a9d8f", "focus_base": "#264653", "fiscal_adverso": "#e76f51"}
PALETA = ["#264653", "#e76f51", "#2a9d8f", "#e9c46a", "#8d99ae", "#6a4c93", "#f4a261"]


def cores(macros):
    extra = iter(c for c in PALETA if c not in CORES_FIXAS.values())
    return {m: CORES_FIXAS.get(m) or next(extra) for m in macros}


def _mes0(res, praca):
    df = next(iter(v for k, v in res.items() if k[1] == praca))
    return df["mes"].iloc[0]


def fig_caixa(res, praca, macros, out):
    cor = cores(macros)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for ax, arq in zip(axes, ARQUETIPOS):
        for m in macros:
            df = res[(m, praca, arq)]
            y = df["inc_caixa_liquido"] / 1e6
            ax.plot(df["t"], y, color=cor[m], lw=2, label=m)
            ins = df.attrs["insolvente_em"]
            if ins is not None:
                ax.scatter([ins], [y.iloc[ins]], color=cor[m], marker="x", s=80, zorder=5)
        ax.axhline(0, color="k", lw=0.8, ls="--")
        ax.set_title(f"{arq}")
        ax.set_xlabel(f"meses desde {_mes0(res, praca)}")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("caixa líquido da construtora (R$ MM)")
    axes[0].legend(fontsize=8)
    fig.suptitle(f"{praca}: caixa por arquétipo e cenário macro (x = insolvência)")
    fig.tight_layout()
    fig.savefig(out / f"caixa_{praca}.png", dpi=130)
    plt.close(fig)


def fig_praca(res, praca, macros, out):
    cor = cores(macros)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for m in macros:
        df = res[(m, praca, "fluxo_dependente")]
        axes[0].plot(df["t"], df["praca_meses_estoque"], color=cor[m], lw=2, label=m)
        axes[1].plot(df["t"], df["praca_preco_m2"] / df["praca_preco_m2"].iloc[0] * 100,
                     color=cor[m], lw=2)
        axes[2].plot(df["t"], df["praca_share_afford"] / df["praca_share_afford"].iloc[0] * 100,
                     color=cor[m], lw=2)
    axes[0].set_title("estoque (meses de venda)"); axes[0].legend(fontsize=8)
    axes[1].set_title("preço/m² nominal (t0 = 100)")
    axes[2].set_title("capacidade de compra do financiado (t0 = 100)")
    for ax in axes:
        ax.set_xlabel(f"meses desde {_mes0(res, praca)}"); ax.grid(alpha=0.3)
    fig.suptitle(f"{praca}: praça sob os cenários (com 1 construtora de fluxo operando)")
    fig.tight_layout()
    fig.savefig(out / f"praca_{praca}.png", dpi=130)
    plt.close(fig)


def fig_fronteira(macros, out, meses):
    cor = cores(macros)
    grid = np.round(np.arange(1.0, 3.01, 0.1), 2)
    fig, axes = plt.subplots(1, len(PRACAS), figsize=(6.5 * len(PRACAS), 4.2), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, praca in zip(axes, PRACAS):
        for m in macros:
            r = vso_minima(m, praca, meses=meses, grid=grid)
            y = [r["detalhe"][g] if r["detalhe"][g] is not None else meses for g in grid]
            ax.plot(grid, y, color=cor[m], lw=2, marker="o", ms=3,
                    label=f"{m} (mín. p/ sobreviver: {r['minimo'] or '>3.0'})")
        ax.axhline(meses, color="k", lw=0.8, ls="--")
        ax.set_title(praca)
        ax.set_xlabel("velocidade de vendas da construtora / velocidade da praça")
        ax.grid(alpha=0.3); ax.legend(fontsize=8)
    axes[0].set_ylabel(f"mês da insolvência (= {meses}: sobrevive)")
    fig.suptitle("Fronteira: quanto acima do mercado a equipe comercial precisa vender "
                 "para o modelo 'obra paga com lançamento' fechar")
    fig.tight_layout()
    fig.savefig(out / "fronteira_vso.png", dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meses", type=int, default=48)
    ap.add_argument("--out", default="out")
    ap.add_argument("--macros", nargs="+", default=list(CENARIOS),
                    help="cenários: nome estilizado, historico:YYYY-MM ou focus:YYYY-MM-DD")
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    res = grade(a.meses, macros=a.macros)
    tab = resumo(res)
    tab.to_csv(out / "resumo_grade.csv", index=False)
    pd.set_option("display.width", 220)
    print(tab.round(1).to_string(index=False))

    for p in PRACAS:
        fig_caixa(res, p, a.macros, out)
        fig_praca(res, p, a.macros, out)
    fig_fronteira(a.macros, out, a.meses)
    print(f"\ngráficos e resumo em {out.resolve()}")


if __name__ == "__main__":
    main()
