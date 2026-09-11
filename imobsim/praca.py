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

from dataclasses import dataclass, field

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
# Configs de praça com os números levantados até aqui
# ---------------------------------------------------------------------------

def lajeado() -> Praca:
    return Praca(
        nome="Lajeado",
        preco_m2=8_103.0,            # Brain/Sinduscom VT, 4T25
        metragem_media=58.0,         # produto encolhendo p/ caber na renda
        renda_comprador=13_500.0,    # família que compra o ticket de ~R$ 470k
        share_financiado=0.80,
        demanda_base_mensal=17.0,    # fluxo estrutural (Univates, indústria)
        estoque_inicial=310.0,       # ~9-10 meses de venda
        lancamentos_externos_mensal=18.0,
        degrau_inicial=260.0,        # famílias realocadas ainda no mercado
        degrau_meia_vida=14.0,
        sens_cdi=1.0,
        cdi_ref=10.0,
        meses_estoque_alvo=9.0,
        alpha_up=0.007,
        alpha_down=0.0025,           # cidade pequena: histerese alta
    )


def balneario_camboriu() -> Praca:
    return Praca(
        nome="Balneario Camboriu",
        preco_m2=15_343.0,           # FipeZap set/2026
        metragem_media=85.0,
        renda_comprador=35_000.0,    # comprador de fora, alta renda
        share_financiado=0.30,
        demanda_base_mensal=90.0,
        estoque_inicial=1_600.0,     # ~18 meses (torres longas)
        lancamentos_externos_mensal=80.0,
        degrau_inicial=0.0,
        sens_cdi=6.0,                # investidor compara com CDI
        cdi_ref=10.0,
        meses_estoque_alvo=15.0,
        alpha_up=0.005,
        alpha_down=0.005,            # mais liquidez, desconto aparece
    )


PRACAS = {"lajeado": lajeado, "balneario_camboriu": balneario_camboriu}
