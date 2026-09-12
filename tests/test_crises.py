"""Stress test com crises: episódios carregam, choques agem, resultado é coerente."""
import pandas as pd
import pytest

from imobsim import EPISODIOS, Choque, grade_stress, resumo_stress, run, stress
from imobsim.crises import episodio


def test_episodios_tem_macro_valido_e_mecanismo():
    for ep in EPISODIOS.values():
        m = ep.cenario()(ep.meses)
        assert len(m) == ep.meses and str(m.index[0]) == ep.inicio
        for col in ("selic", "cdi", "taxa_fin", "incc_aa", "incc_mm"):
            assert col in m.columns and m[col].notna().all()
        assert ep.mecanismo and ep.encaixe in ("forte", "fraco")
        assert all(c.mes < ep.meses for c in ep.choques)


def test_episodio_desconhecido():
    with pytest.raises(KeyError):
        episodio("crise_inventada")


def test_choque_multiplica_e_fixa_atributo():
    base = run("benigno", "lajeado", "capitalizada", meses=12)
    mult = run("benigno", "lajeado", "capitalizada", meses=12,
               choques=[Choque(3, "praca", "demanda_base_mensal", 0.5)])
    fixo = run("benigno", "lajeado", "capitalizada", meses=12,
               choques=[Choque(3, "praca", "confianca", valor=0.5)])
    assert (mult["praca_demanda"].iloc[:3] == base["praca_demanda"].iloc[:3]).all()
    assert mult["praca_demanda"].iloc[3] < base["praca_demanda"].iloc[3]
    assert fixo["praca_confianca"].iloc[3] < base["praca_confianca"].iloc[3]


def test_choque_no_arquetipo_fecha_linha_de_credito():
    sem = stress("intermediaria", "lajeado", "china_2021_23", com_choques=False)
    com = stress("intermediaria", "lajeado", "china_2021_23")
    assert sem.attrs["insolvente_em"] is None
    assert com.attrs["insolvente_em"] is not None


def test_stress_dataframe_tem_episodio_nos_attrs():
    df = stress("capitalizada", "lajeado", "brasil_2014_17")
    assert df.attrs["episodio"] == "brasil_2014_17"
    assert df["mes"].iloc[0] == "2014-01"


def test_grade_stress_e_resumo():
    res = grade_stress(episodios=["brasil_2014_17"], pracas=["lajeado"])
    tab = resumo_stress(res)
    assert len(tab) == 3
    assert set(tab["encaixe"]) == {"forte"}
    cap = tab[tab["arquetipo"] == "capitalizada"].iloc[0]
    assert cap["insolvente_em"] == "sobrevive" and pd.isna(cap["quebra_em_meses"])
