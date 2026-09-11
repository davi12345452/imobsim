"""Testes de fumaça: o modelo roda, é determinístico e mantém as relações
qualitativas descritas no README. Não testam calibração."""
import pandas as pd

from imobsim import ARQUETIPOS, CENARIOS, PRACAS, grade, resumo, run, vso_minima


def test_run_produz_dataframe_mensal():
    df = run("focus_base", "lajeado", "capitalizada", meses=24)
    assert len(df) == 24
    assert df["mes"].iloc[0] == "2026-09"
    for col in ("selic", "taxa_fin", "praca_vso", "inc_caixa_liquido", "inc_insolvente"):
        assert col in df.columns
    assert df.attrs["insolvente_em"] is None


def test_deterministico():
    a = run("fiscal_adverso", "balneario_camboriu", "fluxo_dependente", meses=36)
    b = run("fiscal_adverso", "balneario_camboriu", "fluxo_dependente", meses=36)
    pd.testing.assert_frame_equal(a, b)


def test_grade_cobre_todas_as_combinacoes():
    res = grade(meses=12)
    assert len(res) == len(CENARIOS) * len(PRACAS) * len(ARQUETIPOS)
    tab = resumo(res)
    assert set(tab["arquetipo"]) == set(ARQUETIPOS)


def test_capitalizada_sobrevive_e_fluxo_dependente_quebra():
    res = grade(meses=48, arqs=["capitalizada", "fluxo_dependente"])
    for (m, p, a), df in res.items():
        ins = df.attrs["insolvente_em"]
        if a == "capitalizada":
            assert ins is None, (m, p, a)
        else:
            assert ins is not None, (m, p, a)


def test_insolvencia_congela_o_estado():
    df = run("focus_base", "lajeado", "fluxo_dependente", meses=48)
    ins = df.attrs["insolvente_em"]
    assert ins is not None
    depois = df.loc[df["t"] > ins, "inc_caixa_liquido"]
    assert depois.nunique() == 1


def test_vso_minima_devolve_grid_completo():
    grid = [1.0, 2.0, 3.0]
    r = vso_minima("benigno", "lajeado", meses=24, grid=grid)
    assert set(r["detalhe"]) == set(grid)
    assert r["minimo"] is None or r["minimo"] in grid
