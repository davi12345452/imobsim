"""Roda a grade completa e gera resumo + gráficos.

    python run.py [--meses 48] [--out ./out] [--macros focus_base historico:2014-01 ...]
    python run.py --stress          # stress test com as crises históricas (crises.py)
    python run.py --pracas lajeado exemplos/cidade_exemplo.toml
    python run.py --mc 200          # Monte Carlo (Selic, INCC, degrau, demanda) no 1º macro

Sem `--macros`, usa os três cenários estilizados do estudo original.
"""
from __future__ import annotations

import argparse
import itertools
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from imobsim import (
    ARQUETIPOS,
    CENARIOS,
    EPISODIOS,
    PRACAS,
    grade,
    grade_mc,
    grade_stress,
    resumo,
    resumo_mc,
    resumo_stress,
    sigmas_do_focus,
    vso_minima,
)

CORES_FIXAS = {"benigno": "#2a9d8f", "focus_base": "#264653", "fiscal_adverso": "#e76f51"}
PALETA = ["#e9c46a", "#8d99ae", "#6a4c93", "#f4a261", "#219ebc", "#9b2226", "#606c38"]


def cores(macros):
    extra = itertools.cycle(PALETA)
    return {m: CORES_FIXAS.get(m) or next(extra) for m in macros}


def _rotulo(praca):
    return pathlib.Path(str(praca)).stem


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
    fig.suptitle(f"{_rotulo(praca)}: caixa por arquétipo e cenário macro (x = insolvência)")
    fig.tight_layout()
    fig.savefig(out / f"caixa_{_rotulo(praca)}.png", dpi=130)
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
    fig.suptitle(f"{_rotulo(praca)}: praça sob os cenários (com 1 construtora de fluxo operando)")
    fig.tight_layout()
    fig.savefig(out / f"praca_{_rotulo(praca)}.png", dpi=130)
    plt.close(fig)


def fig_fronteira(macros, pracas, out, meses):
    cor = cores(macros)
    grid = np.round(np.arange(1.0, 3.01, 0.1), 2)
    fig, axes = plt.subplots(1, len(pracas), figsize=(6.5 * len(pracas), 4.2), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, praca in zip(axes, pracas):
        for m in macros:
            r = vso_minima(m, praca, meses=meses, grid=grid)
            y = [r["detalhe"][g] if r["detalhe"][g] is not None else meses for g in grid]
            ax.plot(grid, y, color=cor[m], lw=2, marker="o", ms=3,
                    label=f"{m} (mín. p/ sobreviver: {r['minimo'] or '>3.0'})")
        ax.axhline(meses, color="k", lw=0.8, ls="--")
        ax.set_title(_rotulo(praca))
        ax.set_xlabel("velocidade de vendas da construtora / velocidade da praça")
        ax.grid(alpha=0.3); ax.legend(fontsize=8)
    axes[0].set_ylabel(f"mês da insolvência (= {meses}: sobrevive)")
    fig.suptitle("Fronteira: quanto acima do mercado a equipe comercial precisa vender "
                 "para o modelo 'obra paga com lançamento' fechar")
    fig.tight_layout()
    fig.savefig(out / "fronteira_vso.png", dpi=130)
    plt.close(fig)


def fig_stress(res, tab, out):
    """Mapa arquétipo x episódio (mês relativo da quebra) e caixa de cada arquétipo
    em Lajeado sob cada episódio."""
    eps = list(EPISODIOS)
    arqs = list(ARQUETIPOS)
    pracas = list(dict.fromkeys(k[1] for k in res))
    fig, axes = plt.subplots(1, len(pracas), figsize=(6.8 * len(pracas), 3.6))
    axes = np.atleast_1d(axes)
    for ax, praca in zip(axes, pracas):
        mat = np.full((len(arqs), len(eps)), np.nan)
        for i, a in enumerate(arqs):
            for j, e in enumerate(eps):
                mat[i, j] = res[(e, praca, a)].attrs["insolvente_em"] or np.nan
        show = np.where(np.isnan(mat), np.nanmax(mat) + 12, mat)
        ax.imshow(show, cmap="RdYlGn", vmin=0, vmax=np.nanmax(mat) + 12, aspect="auto")
        for i in range(len(arqs)):
            for j in range(len(eps)):
                txt = "sobrevive" if np.isnan(mat[i, j]) else f"mês {int(mat[i, j])}"
                ax.text(j, i, txt, ha="center", va="center", fontsize=8)
        ax.set_xticks(range(len(eps)))
        ax.set_xticklabels([f"{e}\n({EPISODIOS[e].encaixe})" for e in eps], fontsize=7)
        ax.set_yticks(range(len(arqs))); ax.set_yticklabels(arqs, fontsize=8)
        ax.set_title(_rotulo(praca))
    fig.suptitle("Stress test: mês da insolvência sob cada crise histórica "
                 "(praça de hoje, macro e choques da época)")
    fig.tight_layout()
    fig.savefig(out / "stress_crises.png", dpi=130)
    plt.close(fig)

    cor = cores(eps)
    p0 = pracas[0]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for ax, arq in zip(axes, arqs):
        for e in eps:
            df = res[(e, p0, arq)]
            y = df["inc_caixa_liquido"] / 1e6
            ax.plot(df["t"], y, color=cor[e], lw=2, label=e)
            ins = df.attrs["insolvente_em"]
            if ins is not None:
                ax.scatter([ins], [y.iloc[ins]], color=cor[e], marker="x", s=80, zorder=5)
        ax.axhline(0, color="k", lw=0.8, ls="--")
        ax.set_title(arq); ax.set_xlabel("meses desde o início do episódio"); ax.grid(alpha=0.3)
    axes[0].set_ylabel("caixa líquido (R$ MM)"); axes[0].legend(fontsize=8)
    fig.suptitle(f"{_rotulo(p0)}: caixa de cada arquétipo sob cada crise (x = insolvência)")
    fig.tight_layout()
    fig.savefig(out / f"stress_caixa_{_rotulo(p0)}.png", dpi=130)
    plt.close(fig)


def fig_mc(res, out, meses):
    pracas = list(dict.fromkeys(k[0] for k in res))
    arqs = list(dict.fromkeys(k[1] for k in res))
    fig, axes = plt.subplots(len(pracas), len(arqs), figsize=(5 * len(arqs), 3.4 * len(pracas)),
                             squeeze=False, sharex=True)
    for i, p in enumerate(pracas):
        for j, a in enumerate(arqs):
            ax = axes[i, j]
            df = res[(p, a)]
            meses_q = df["insolvente_em"].dropna()
            ax.hist(meses_q, bins=range(0, meses + 2, 2), color="#e76f51", alpha=0.85)
            prob = df.attrs["prob_quebra"]
            ax.text(0.02, 0.92, f"P(quebra em {meses}m) = {prob:.0%}\nn = {len(df)}",
                    transform=ax.transAxes, va="top", fontsize=9)
            ax.set_title(f"{_rotulo(p)} · {a}", fontsize=10)
            ax.set_xlim(0, meses); ax.grid(alpha=0.3)
            if meses_q.empty:
                ax.set_ylim(0, 1)
                ax.text(0.5, 0.45, "nenhuma quebra", transform=ax.transAxes, ha="center",
                        fontsize=10, color="#2a9d8f")
            if i == len(pracas) - 1:
                ax.set_xlabel("mês da insolvência")
            if j == 0:
                ax.set_ylabel("rodadas")
    fig.suptitle("Monte Carlo: Selic, INCC, degrau e demanda base sorteados em torno do cenário")
    fig.tight_layout()
    fig.savefig(out / "mc_quebra.png", dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meses", type=int, default=48)
    ap.add_argument("--out", default="out")
    ap.add_argument("--macros", nargs="+", default=list(CENARIOS),
                    help="cenários: nome estilizado, historico:YYYY-MM ou focus:YYYY-MM-DD")
    ap.add_argument("--pracas", nargs="+", default=list(PRACAS),
                    help="praças: nome em imobsim/pracas/ ou caminho para um .toml")
    ap.add_argument("--stress", action="store_true",
                    help="em vez da grade, roda o stress test com as crises históricas")
    ap.add_argument("--mc", type=int, default=0, metavar="N",
                    help="em vez da grade, roda N amostras de Monte Carlo no primeiro macro")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)

    if a.mc:
        sig = sigmas_do_focus("2026-09-04")
        res = grade_mc(a.macros[0], pracas=a.pracas, n=a.mc, seed=a.seed, meses=a.meses,
                       sigmas=sig)
        tab = pd.DataFrame([resumo_mc(df) for df in res.values()])
        tab.to_csv(out / "mc_resumo.csv", index=False)
        print(f"sigmas: {sig}")
        print(tab.round(2).to_string(index=False))
        fig_mc(res, out, a.meses)
        print(f"\nmonte carlo em {out.resolve()}")
        return

    if a.stress:
        res = grade_stress(pracas=a.pracas)
        tab = resumo_stress(res)
        tab.to_csv(out / "stress_crises.csv", index=False)
        print(tab.round(1).to_string(index=False))
        fig_stress(res, tab, out)
        print(f"\nstress em {out.resolve()}")
        return

    res = grade(a.meses, macros=a.macros, pracas=a.pracas)
    tab = resumo(res)
    tab.to_csv(out / "resumo_grade.csv", index=False)
    print(tab.round(1).to_string(index=False))

    for p in a.pracas:
        fig_caixa(res, p, a.macros, out)
        fig_praca(res, p, a.macros, out)
    fig_fronteira(a.macros, a.pracas, out, a.meses)
    print(f"\ngráficos e resumo em {out.resolve()}")


if __name__ == "__main__":
    main()
