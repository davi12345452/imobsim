"""Praça: o mercado local.

Cada praça define QUAL canal macro morde sua demanda:
  - comprador financiado  -> taxa SBPE vs renda (Lajeado)
  - comprador investidor  -> CDI como custo de oportunidade (Balneário Camboriú)

A demanda tem duas partes:
  - fluxo base   (formação de domicílios, migração)
  - degrau       (demanda de evento, ex.: famílias realocadas pela enchente,
                  decai exponencialmente à medida que se realocam)

Preço tem histerese: sobe rápido com estoque baixo, cai devagar com estoque
alto (ninguém baixa tabela, dá desconto no balcão).
"""
from __future__ import annotations

import pathlib
import tomllib
from dataclasses import dataclass, field, fields, replace

import numpy as np


def parcela_price(principal: float, taxa_aa: float, n: int = 360) -> float:
    i = (1 + taxa_aa / 100) ** (1 / 12) - 1
    return principal * i / (1 - (1 + i) ** -n)


def logistica(x: float, k: float = 6.0, x0: float = 1.0) -> float:
    return 1.0 / (1.0 + np.exp(-k * (x - x0)))


@dataclass
class Praca:
    nome: str
    preco_m2: float                 # R$/m² lançamento
    metragem_media: float           # m² privativo
    renda_comprador: float          # renda familiar do comprador marginal (R$/mês)
    share_financiado: float         # fração que compra via SBPE
    demanda_base_mensal: float      # unidades/mês em condições "normais"
    estoque_inicial: float          # unidades novas à venda (planta+obra+pronto)
    lancamentos_externos_mensal: float  # lançamentos do resto do mercado
    degrau_inicial: float = 0.0     # demanda de evento ainda não absorvida
    degrau_meia_vida: float = 12.0  # meses
    sens_cdi: float = 0.0           # elasticidade do investidor ao CDI
    cdi_ref: float = 10.0
    meses_estoque_alvo: float = 9.0
    alpha_up: float = 0.012         # velocidade de alta de preço
    alpha_down: float = 0.004       # velocidade de queda (histerese)
    passthrough_incc: float = 0.5   # quanto do INCC a construtora tenta repassar
    comprometimento_max: float = 0.30
    entrada_pct: float = 0.20

    # estado
    preco: float = field(init=False)
    estoque: float = field(init=False)
    degrau: float = field(init=False)
    confianca: float = 1.0
    share_afford_ref: float | None = field(default=None, init=False)  # fixado em t0
    hist: list = field(default_factory=list, init=False)

    def __post_init__(self):
        self.preco = self.preco_m2
        self.estoque = self.estoque_inicial
        self.degrau = self.degrau_inicial

    # ---- capacidade de compra -------------------------------------------
    def share_afford(self, taxa_fin: float) -> float:
        ticket = self.preco * self.metragem_media
        financiado = ticket * (1 - self.entrada_pct)
        parcela = parcela_price(financiado, taxa_fin)
        parcela_max = self.comprometimento_max * self.renda_comprador
        return float(logistica(parcela_max / parcela))

    def fator_investidor(self, cdi: float) -> float:
        return float(np.exp(-self.sens_cdi * (cdi - self.cdi_ref) / 100))

    # ---- um passo mensal --------------------------------------------------
    def demanda(self, macro_t) -> tuple[float, float]:
        sa = self.share_afford(macro_t.taxa_fin)
        if self.share_afford_ref is None:
            self.share_afford_ref = sa  # normaliza: t0 = condições "atuais"
        f_fin = sa / self.share_afford_ref
        f_inv = self.fator_investidor(macro_t.cdi)
        f_base = self.share_financiado * f_fin + (1 - self.share_financiado) * f_inv
        base = self.demanda_base_mensal * f_base * self.confianca

        # degrau: famílias realocadas dependem de FGTS/MCMV, menos sensíveis à taxa
        absorcao = self.degrau * (1 - 0.5 ** (1 / self.degrau_meia_vida))
        absorcao *= (0.6 + 0.4 * f_fin) * self.confianca
        return base + absorcao, sa

    def step(self, macro_t, novas_unidades: float, choque_confianca: float = 0.0):
        dem, sa = self.demanda(macro_t)
        vendas = min(dem, self.estoque)
        vso = vendas / self.estoque if self.estoque > 0 else 0.0

        # atualiza degrau (absorvido o que foi vendido dessa parcela)
        parte_degrau = self.degrau * (1 - 0.5 ** (1 / self.degrau_meia_vida))
        self.degrau = max(0.0, self.degrau - parte_degrau)

        self.estoque += novas_unidades + self.lancamentos_externos_mensal - vendas
        meses = self.estoque / max(vendas, 1e-6)

        # preço: histerese + tentativa de repasse de INCC
        gap = (self.meses_estoque_alvo - meses) / self.meses_estoque_alvo
        if gap > 0:
            self.preco *= 1 + self.alpha_up * min(gap, 1.0)
        else:
            self.preco *= 1 + self.alpha_down * max(gap, -2.0)
        self.preco *= 1 + self.passthrough_incc * macro_t.incc_mm

        # confiança: choque e recuperação lenta
        if choque_confianca > 0:
            self.confianca *= 1 - choque_confianca
        self.confianca += 0.04 * (1 - self.confianca)

        rec = dict(
            demanda=dem, vendas=vendas, vso=vso, estoque=self.estoque,
            meses_estoque=meses, preco_m2=self.preco, share_afford=sa,
            confianca=self.confianca, degrau=self.degrau,
        )
        self.hist.append(rec)
        return rec


# ---------------------------------------------------------------------------
# Praças a partir de arquivo (TOML) e de observáveis públicos
# ---------------------------------------------------------------------------

PRACAS_DIR = pathlib.Path(__file__).parent / "pracas"
_CAMPOS_INIT = {f.name for f in fields(Praca) if f.init}

# Tipo de praça: o que define QUAL canal macro morde e como o preço reage.
# Os campos "derivacao" só são usados por Praca.from_dados.
TEMPLATES: dict[str, dict] = {
    "interior": dict(
        # cidade média do interior: comprador local, financiado, produto encolhe p/ caber na renda
        share_financiado=0.80, sens_cdi=1.0, cdi_ref=10.0, meses_estoque_alvo=9.0,
        alpha_up=0.007, alpha_down=0.0025, passthrough_incc=0.5,
        comprometimento_max=0.30, entrada_pct=0.20,
        derivacao=dict(metragem_media=58.0, mult_renda=3.0, share_novos=0.40,
                       fator_externos=1.05),
    ),
    "litoral_investidor": dict(
        # capital/litoral de investidor: comprador de fora, à vista, compara com CDI
        share_financiado=0.30, sens_cdi=6.0, cdi_ref=10.0, meses_estoque_alvo=15.0,
        alpha_up=0.005, alpha_down=0.005, passthrough_incc=0.5,
        comprometimento_max=0.30, entrada_pct=0.20,
        derivacao=dict(metragem_media=85.0, mult_renda=6.0, share_novos=0.45,
                       fator_externos=0.90),
    ),
    "metropole": dict(
        # capital grande: mistura de financiado e investidor, mercado líquido
        share_financiado=0.60, sens_cdi=3.0, cdi_ref=10.0, meses_estoque_alvo=12.0,
        alpha_up=0.006, alpha_down=0.004, passthrough_incc=0.5,
        comprometimento_max=0.30, entrada_pct=0.20,
        derivacao=dict(metragem_media=65.0, mult_renda=3.5, share_novos=0.40,
                       fator_externos=1.00),
    ),
}


def _valida_campos(d: dict, origem: str):
    extras = set(d) - _CAMPOS_INIT
    if extras:
        raise ValueError(f"{origem}: campos desconhecidos {sorted(extras)}. "
                         f"Válidos: {sorted(_CAMPOS_INIT)}")


def from_dados(nome: str, tipo: str, preco_m2: float, renda_domiciliar_mediana: float,
               domicilios: float, crescimento_domicilios_aa: float,
               degrau_inicial: float = 0.0, degrau_meia_vida: float = 12.0,
               **overrides) -> Praca:
    """Monta uma praça a partir de observáveis públicos e de um template de tipo.

    Entradas (todas de fontes públicas):
        preco_m2                    FipeZap / Sinduscon regional (R$/m² de lançamento)
        renda_domiciliar_mediana    Censo 2022 / PNAD (R$/mês)
        domicilios                  Censo 2022 (domicílios particulares ocupados)
        crescimento_domicilios_aa   fração ao ano (Censo 2010 -> 2022, ou projeção IBGE)
        degrau_inicial              demanda de evento ainda não absorvida (unidades)

    Derivação (heurísticas do template, todas sobrescritíveis por `overrides`):
        renda_comprador     = mult_renda x renda mediana   (comprador marginal de imóvel novo
                              está bem acima da mediana; 3x no interior, 6x em praça de investidor)
        demanda_base_mensal = domicilios x crescimento x share_novos / 12
                              (fração da formação de domicílios atendida por imóvel novo)
        lancamentos_externos_mensal = demanda_base x fator_externos
        estoque_inicial     = (demanda_base + absorção inicial do degrau) x meses_estoque_alvo

    O que NÃO vem de dado público e você deve calibrar: estoque real (Abrainc só
    cobre capitais), VSO efetiva, e a renda do comprador marginal. Trate a saída
    como ponto de partida, não como calibração.
    """
    if tipo not in TEMPLATES:
        raise KeyError(f"tipo desconhecido: {tipo!r}. Use um de {list(TEMPLATES)}")
    tpl = {k: v for k, v in TEMPLATES[tipo].items() if k != "derivacao"}
    der = TEMPLATES[tipo]["derivacao"]
    meses_alvo = overrides.get("meses_estoque_alvo", tpl["meses_estoque_alvo"])
    demanda = domicilios * crescimento_domicilios_aa * der["share_novos"] / 12
    absorcao0 = degrau_inicial * (1 - 0.5 ** (1 / degrau_meia_vida))
    params = dict(
        nome=nome, preco_m2=float(preco_m2),
        metragem_media=der["metragem_media"],
        renda_comprador=der["mult_renda"] * renda_domiciliar_mediana,
        demanda_base_mensal=demanda,
        estoque_inicial=(demanda + absorcao0) * meses_alvo,
        lancamentos_externos_mensal=demanda * der["fator_externos"],
        degrau_inicial=degrau_inicial, degrau_meia_vida=degrau_meia_vida,
        **tpl,
    )
    params.update(overrides)
    _valida_campos(params, f"from_dados({nome})")
    return Praca(**params)


def from_toml(path: str | pathlib.Path) -> Praca:
    """Carrega uma praça de um TOML.

    Duas formas:
      - campos diretos do dataclass (`preco_m2 = 8103.0`, ...), ou
      - `tipo = "interior"` + tabela `[dados]` com as entradas de `from_dados`;
        campos soltos fora de `[dados]` viram overrides.
    """
    path = pathlib.Path(path)
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    cfg.pop("ordem", None)  # só afeta a ordem em carregar_pracas
    cfg.setdefault("nome", path.stem)
    if "dados" in cfg:
        dados = cfg.pop("dados")
        tipo = cfg.pop("tipo")
        nome = cfg.pop("nome")
        return from_dados(nome, tipo, **dados, **cfg)
    _valida_campos(cfg, str(path))
    return Praca(**cfg)


def carregar_pracas(diretorio: str | pathlib.Path = PRACAS_DIR) -> dict:
    """{stem: factory} para cada *.toml do diretório, na ordem do campo opcional
    `ordem` (depois por nome). Factory devolve instância nova a cada chamada."""
    arquivos = []
    for f in pathlib.Path(diretorio).glob("*.toml"):
        with open(f, "rb") as fh:
            ordem = tomllib.load(fh).get("ordem", 1_000)
        arquivos.append((ordem, f.stem, f))
    return {stem: (lambda p=f: from_toml(p)) for _, stem, f in sorted(arquivos)}


PRACAS = carregar_pracas()


def praca(spec):
    """Resolve uma especificação de praça para um factory() -> Praca nova.

    Aceita: nome em PRACAS ("lajeado"), caminho para .toml, uma instância de
    Praca (é copiada limpa a cada chamada) ou um callable sem argumentos."""
    if isinstance(spec, Praca):
        return lambda: replace(spec)
    if callable(spec):
        return spec
    if spec in PRACAS:
        return PRACAS[spec]
    p = pathlib.Path(str(spec))
    if p.suffix == ".toml" and p.exists():
        return lambda: from_toml(p)
    raise KeyError(f"praça desconhecida: {spec!r}. Use um de {list(PRACAS)} ou um caminho .toml")


def lajeado() -> Praca:
    return PRACAS["lajeado"]()


def balneario_camboriu() -> Praca:
    return PRACAS["balneario_camboriu"]()
