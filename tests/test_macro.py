"""Cenários a partir de dados: rodam offline com o snapshot do pacote."""
import numpy as np
import pandas as pd
import pytest

from imobsim import CENARIOS, cenario, focus, fontes, historico, run


def test_snapshot_sgs_carrega_offline():
    df = fontes.sgs()
    assert list(df.columns) == ["selic", "incc_mm", "ipca_mm", "taxa_fin"]
    assert df.index[0] == pd.Period("1994-07", "M")
    assert df.loc["2014-01", "selic"] == pytest.approx(10.17)
    assert df.loc["2014-01", "taxa_fin"] == pytest.approx(9.52)
    assert np.isnan(df.loc["2010-12", "taxa_fin"])  # série 20774 começa em mar/2011


def test_historico_usa_sbpe_observada_e_regra_antes_de_2011():
    h = historico("2014-01", 48)
    assert len(h) == 48 and h.index[0] == pd.Period("2014-01", "M")
    assert h["taxa_fin"].iloc[0] == pytest.approx(9.52)
    assert h.attrs["nome"] == "historico:2014-01"
    antigo = historico("2005-01", 12)
    assert antigo["taxa_fin"].iloc[0] == pytest.approx(5 + 0.55 * antigo["selic"].iloc[0])


def test_historico_alem_do_snapshot_exige_estender():
    ultimo = fontes.sgs().index[-1]
    with pytest.raises(ValueError):
        historico(str(ultimo - 5), 12)
    h = historico(str(ultimo - 5), 12, estender=True)
    assert len(h) == 12
    assert h["selic"].iloc[-1] == h["selic"].iloc[5]


def test_focus_passa_pelas_medianas_de_dezembro():
    f = focus("2026-09-04", 48)
    exp = fontes.focus("2026-09-04", "Selic")
    assert f.index[0] == pd.Period("2026-10", "M")
    for ano, med in zip(exp["ano"], exp["mediana"]):
        dez = pd.Period(f"{ano}-12", "M")
        if dez in f.index:
            assert f.loc[dez, "selic"] == pytest.approx(med)
    assert f["selic"].iloc[-1] == pytest.approx(exp["mediana"].iloc[-1])
    # SBPE parte do último valor observado, não da regra
    sbpe_obs = fontes.sgs()["taxa_fin"].dropna().iloc[-1]
    assert f["taxa_fin"].iloc[0] == pytest.approx(sbpe_obs, abs=0.3)


def test_cenario_resolve_strings_callables_e_dataframes():
    assert cenario("focus_base") is CENARIOS["focus_base"]
    assert cenario("historico:2014-01")(6).attrs["nome"] == "historico:2014-01"
    df = CENARIOS["benigno"](24)
    assert len(cenario(df)(12)) == 12
    assert cenario(lambda n: df)(5) is df
    with pytest.raises(KeyError):
        cenario("inexistente")


def test_run_aceita_historico():
    df = run("historico:2014-01", "lajeado", "capitalizada", meses=36)
    assert df["mes"].iloc[0] == "2014-01"
    assert df.attrs["macro"] == "historico:2014-01"
