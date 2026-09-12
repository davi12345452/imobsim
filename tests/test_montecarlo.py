"""Monte Carlo: determinístico por seed, degenera para a rodada base com sigma 0."""
import numpy as np
import pandas as pd

from imobsim import Sigmas, grade_mc, monte_carlo, resumo_mc, run, sigmas_do_focus


def test_seed_reproduz():
    a = monte_carlo("focus_base", "lajeado", "fluxo_dependente", n=8, seed=1, meses=24)
    b = monte_carlo("focus_base", "lajeado", "fluxo_dependente", n=8, seed=1, meses=24)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 8 and 0.0 <= a.attrs["prob_quebra"] <= 1.0


def test_sigma_zero_reproduz_rodada_deterministica():
    zero = Sigmas(0, 0, 0, 0)
    mc = monte_carlo("focus_base", "lajeado", "fluxo_dependente", n=3, seed=0, sigmas=zero)
    base = run("focus_base", "lajeado", "fluxo_dependente")
    assert (mc["insolvente_em"] == base.attrs["insolvente_em"]).all()
    assert np.allclose(mc["fator_degrau"], 1.0) and np.allclose(mc["fator_demanda"], 1.0)


def test_capitalizada_quase_nunca_quebra_e_resumo_tem_sensibilidade():
    mc = monte_carlo("focus_base", "lajeado", "capitalizada", n=30, seed=2, meses=36)
    r = resumo_mc(mc)
    assert r["prob_quebra"] <= 0.1
    assert set(k for k in r if k.startswith("sens_")) == {
        "sens_selic_desvio_base", "sens_incc_medio", "sens_fator_degrau", "sens_fator_demanda"}


def test_sigmas_do_focus_offline():
    s = sigmas_do_focus("2026-09-04")
    assert 0.3 < s.selic_12m < 2.0 and 0.3 < s.incc_12m < 2.0


def test_grade_mc_chaves():
    res = grade_mc("benigno", pracas=["lajeado"], n=4, seed=0, meses=12)
    arqs = ("fluxo_dependente", "intermediaria", "capitalizada")
    assert set(res) == {("lajeado", a) for a in arqs}
