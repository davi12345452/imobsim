"""Praças por arquivo, templates e derivação de observáveis."""
import pathlib

import pytest

from imobsim import PRACAS, TEMPLATES, Praca, from_dados, from_toml, praca, run


def test_toml_reproduz_parametros_originais():
    lj = PRACAS["lajeado"]()
    assert (lj.preco_m2, lj.renda_comprador, lj.estoque_inicial) == (8103.0, 13500.0, 310.0)
    assert lj.degrau_inicial == 260.0 and lj.alpha_down == 0.0025
    bc = PRACAS["balneario_camboriu"]()
    assert bc.sens_cdi == 6.0 and bc.share_financiado == 0.30
    assert list(PRACAS) == ["lajeado", "balneario_camboriu"]  # campo `ordem`


def test_factory_devolve_instancia_nova():
    a, b = PRACAS["lajeado"](), PRACAS["lajeado"]()
    a.estoque = 0
    assert b.estoque == 310.0


def test_from_dados_interior_reproduz_lajeado_aproximadamente():
    d = from_dados("Lajeado", "interior", preco_m2=8103, renda_domiciliar_mediana=4500,
                   domicilios=35_000, crescimento_domicilios_aa=0.015,
                   degrau_inicial=260, degrau_meia_vida=14)
    assert d.renda_comprador == pytest.approx(13_500)
    assert d.demanda_base_mensal == pytest.approx(17.5, abs=0.1)
    assert d.lancamentos_externos_mensal == pytest.approx(18.4, abs=0.1)
    assert 250 < d.estoque_inicial < 320
    assert d.share_financiado == TEMPLATES["interior"]["share_financiado"]


def test_from_dados_overrides_e_erros():
    d = from_dados("X", "metropole", 9000, 5000, 500_000, 0.01, estoque_inicial=999.0)
    assert d.estoque_inicial == 999.0
    with pytest.raises(KeyError):
        from_dados("X", "tipo_inexistente", 9000, 5000, 1, 0.01)
    with pytest.raises(ValueError):
        from_dados("X", "interior", 9000, 5000, 1, 0.01, campo_que_nao_existe=1)


def test_from_toml_com_secao_dados(tmp_path: pathlib.Path):
    f = tmp_path / "minha.toml"
    f.write_text('tipo = "litoral_investidor"\nmeses_estoque_alvo = 20.0\n'
                 '[dados]\npreco_m2 = 12000\nrenda_domiciliar_mediana = 6000\n'
                 'domicilios = 60000\ncrescimento_domicilios_aa = 0.04\n')
    p = from_toml(f)
    assert p.nome == "minha" and p.meses_estoque_alvo == 20.0
    assert p.renda_comprador == pytest.approx(36_000)


def test_from_toml_rejeita_campo_desconhecido(tmp_path: pathlib.Path):
    f = tmp_path / "ruim.toml"
    f.write_text('preco_m2 = 1.0\ncampo_errado = 2\n')
    with pytest.raises(ValueError):
        from_toml(f)


def test_resolvedor_aceita_nome_caminho_instancia_e_factory():
    assert praca("lajeado") is PRACAS["lajeado"]
    ex = praca("exemplos/cidade_exemplo.toml")()
    assert isinstance(ex, Praca) and ex.nome == "Cidade Exemplo"
    inst = PRACAS["lajeado"]()
    inst.estoque = 1.0
    assert praca(inst)().estoque == 310.0  # cópia limpa, não o objeto usado
    assert praca(lambda: inst)() is inst
    with pytest.raises(KeyError):
        praca("nao_existe")


def test_run_por_caminho_toml():
    df = run("focus_base", "exemplos/cidade_exemplo.toml", "capitalizada", meses=12)
    assert df.attrs["praca"] == "Cidade Exemplo"
