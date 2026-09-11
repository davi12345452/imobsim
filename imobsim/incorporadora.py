"""Incorporadora: caixa, obras, funding e política de lançamento.

A regra que tangibiliza "obra de hoje paga com lançamento de agora":

    afetacao=False  -> caixa único (pool). Recebíveis do lançamento B pagam
                       a obra de A. Solvência depende de continuar lançando.
    afetacao=True   -> caixa por SPE. Cada obra vive do próprio recebível +
                       plano empresário. A holding só cobre com sua reserva.

Fluxo do comprador (planta):
    entrada (20%)  -> na venda
    obra   (20%)   -> parcelas até a entrega, corrigidas por INCC
    repasse (60%)  -> na entrega, SE o banco aprova (renda vs taxa vigente)
                      senão distrato: devolve 50% do pago em 6 meses,
                      unidade volta ao estoque como "pronto".
"""
from __future__ import annotations

from dataclasses import dataclass, field


def curva_s(k: int, dur: int) -> float:
    """Fração acumulada de custo de obra desembolsada até o mês k."""
    if k <= 0:
        return 0.0
    if k >= dur:
        return 1.0
    s = k / dur
    return 3 * s**2 - 2 * s**3


@dataclass
class Arquetipo:
    nome: str
    afetacao: bool
    reserva_inicial: float        # R$ caixa próprio em t0
    limite_credito: float         # linha rotativa corporativa (R$)
    pe_pct: float                 # % do desembolso coberto por plano empresário
    spread_pe: float              # p.p. ao ano sobre CDI
    n_unidades_inicial: int
    crescimento_lanc: float       # fator de tamanho a cada novo lançamento
    lanc_intervalo: int           # meses entre lançamentos
    politica: str                 # "fluxo" | "prudente"
    fator_vendas: float = 1.0     # velocidade relativa à praça
    custo_pct: float = 0.55       # custo de obra / VGV
    terreno_pct: float = 0.15     # terreno / VGV
    permuta_pct: float = 0.50     # parte do terreno paga em unidades
    duracao_obra: int = 30
    projetos_iniciais: tuple = ()  # [(meses_desde_lanc, n_unidades, frac_vendida)]
    max_obras: int = 4


@dataclass
class Empreendimento:
    eid: int
    mes_lanc: int
    n_unidades: int
    preco_unit: float
    custo_total: float
    duracao: int
    afetacao: bool
    vendidas: int = 0
    prontas_estoque: int = 0      # distratadas, à venda como pronto
    entregue: bool = False
    caixa_spe: float = 0.0
    divida_pe: float = 0.0
    recebido_por_unidade: float = 0.0
    carteira_obra: float = 0.0    # saldo a receber em parcelas de obra
    devolucoes_pendentes: list = field(default_factory=list)  # [(mes, valor)]
    parada: bool = False

    @property
    def vgv(self):
        return self.n_unidades * self.preco_unit

    @property
    def estoque(self):
        return self.n_unidades - self.vendidas + self.prontas_estoque

    def em_obra(self, t):
        return not self.entregue and not self.parada and t >= self.mes_lanc


class Incorporadora:
    def __init__(self, arq: Arquetipo, praca, t0: int = 0):
        self.arq = arq
        self.pool = arq.reserva_inicial
        self.divida_corp = 0.0
        self.obras: list[Empreendimento] = []
        self.insolvente_em: int | None = None
        self.ultimo_lanc = -arq.lanc_intervalo
        self.hist: list = []
        self._eid = 0
        # projetos já em andamento em t0 ("obra de hoje")
        for meses_desde, n, frac in arq.projetos_iniciais:
            e = self._novo(-meses_desde, n, praca.preco * praca.metragem_media * 0.9)
            e.vendidas = int(n * frac)
            # já recebeu entrada + parte da obra dos vendidos; já gastou parte da obra
            gasto = e.custo_total * curva_s(meses_desde, e.duracao)
            recebido = e.vendidas * e.preco_unit * (0.20 + 0.20 * meses_desde / e.duracao)
            e.divida_pe = gasto * arq.pe_pct
            saldo = recebido - gasto * (1 - arq.pe_pct)
            if arq.afetacao:
                e.caixa_spe += saldo
            else:
                self.pool += saldo
            e.carteira_obra = e.vendidas * e.preco_unit * 0.20 * (1 - meses_desde / e.duracao)
            self.ultimo_lanc = max(self.ultimo_lanc, -meses_desde)

    # ------------------------------------------------------------------
    def _novo(self, t: int, n: int, preco_unit: float) -> Empreendimento:
        self._eid += 1
        vgv = n * preco_unit
        e = Empreendimento(
            eid=self._eid, mes_lanc=t, n_unidades=n, preco_unit=preco_unit,
            custo_total=vgv * self.arq.custo_pct, duracao=self.arq.duracao_obra,
            afetacao=self.arq.afetacao,
        )
        self.obras.append(e)
        return e

    def _pagar(self, e: Empreendimento, valor: float, t: int):
        """Desembolso: SPE segregada ou pool. Retorna True se conseguiu."""
        if self.arq.afetacao:
            if e.caixa_spe >= valor:
                e.caixa_spe -= valor
                return True
            falta = valor - e.caixa_spe
            e.caixa_spe = 0.0
            # holding cobre com reserva/linha
            if self.pool + (self.arq.limite_credito - self.divida_corp) >= falta:
                self._sacar_pool(falta)
                return True
            return False
        else:
            if self.pool + (self.arq.limite_credito - self.divida_corp) >= valor:
                self._sacar_pool(valor)
                return True
            return False

    def _sacar_pool(self, valor):
        if self.pool >= valor:
            self.pool -= valor
        else:
            self.divida_corp += valor - self.pool
            self.pool = 0.0

    def _receber(self, e: Empreendimento, valor: float):
        if self.arq.afetacao:
            e.caixa_spe += valor
        else:
            self.pool += valor

    # ------------------------------------------------------------------
    def _deve_lancar(self, t: int) -> bool:
        if t - self.ultimo_lanc < self.arq.lanc_intervalo:
            return False
        ativas = [e for e in self.obras if e.em_obra(t)]
        if len(ativas) >= self.arq.max_obras:
            return False
        if self.arq.politica == "fluxo":
            return True
        # prudente: só lança se o estoque próprio está baixo
        est = sum(e.estoque for e in self.obras if not e.parada)
        tot = sum(e.n_unidades for e in self.obras if not e.parada) or 1
        return est / tot < 0.30

    def step(self, t: int, macro_t, vso: float, share_afford: float, praca) -> dict:
        if self.insolvente_em is not None:
            return self._rec(t, novas=0, vendas=0)

        arq = self.arq
        cdi_mm = (1 + macro_t.cdi / 100) ** (1 / 12) - 1
        novas_unidades = 0

        # ---- lançamento ------------------------------------------------
        if self._deve_lancar(t):
            n_prev = max((e.n_unidades for e in self.obras), default=arq.n_unidades_inicial)
            n = int(round(n_prev * arq.crescimento_lanc)) if self.obras else arq.n_unidades_inicial
            preco_unit = praca.preco * praca.metragem_media
            e = self._novo(t, n, preco_unit)
            terreno_cash = e.vgv * arq.terreno_pct * (1 - arq.permuta_pct)
            permuta_unid = int(round(n * arq.terreno_pct * arq.permuta_pct))
            e.n_unidades -= permuta_unid  # unidades vão ao dono do terreno
            if not self._pagar(e, terreno_cash, t):
                self.insolvente_em = t
                return self._rec(t, novas=0, vendas=0)
            self.ultimo_lanc = t
            novas_unidades = n  # todas entram no estoque da praça

        vendas_mes = 0
        # ---- cada obra ------------------------------------------------
        for e in self.obras:
            if e.parada:
                continue
            k = t - e.mes_lanc

            # vendas (planta ou pronto): proporcional à VSO da praça
            if e.estoque > 0:
                v = min(e.estoque, vso * e.estoque * arq.fator_vendas)
                v_int = int(v) + (1 if (v - int(v)) > 0.5 else 0)
                for _ in range(v_int):
                    if e.prontas_estoque > 0:
                        e.prontas_estoque -= 1  # pronto: recebe 100% via repasse imediato
                        self._receber(e, e.preco_unit * 0.95)  # desconto de balcão
                    else:
                        e.vendidas += 1
                        self._receber(e, e.preco_unit * 0.20)  # entrada
                        e.carteira_obra += e.preco_unit * 0.20
                vendas_mes += v_int

            if e.entregue:
                continue

            # parcelas de obra (corrigidas por INCC)
            rest = max(e.duracao - k, 1)
            e.carteira_obra *= 1 + macro_t.incc_mm
            parcela = e.carteira_obra / rest
            e.carteira_obra -= parcela
            self._receber(e, parcela)

            # desembolso de obra + juros do plano empresário
            desemb = e.custo_total * (curva_s(k, e.duracao) - curva_s(k - 1, e.duracao))
            desemb *= (1 + macro_t.incc_mm) ** max(k, 0)  # custo sobe com INCC
            juros_pe = e.divida_pe * (cdi_mm + arq.spread_pe / 100 / 12)
            pe_novo = desemb * arq.pe_pct
            e.divida_pe += pe_novo
            a_pagar = desemb * (1 - arq.pe_pct) + juros_pe
            if not self._pagar(e, a_pagar, t):
                e.parada = True
                self.insolvente_em = t
                break

            # entrega e repasse
            if k >= e.duracao:
                e.entregue = True
                aprovados = int(round(e.vendidas * share_afford_repasse(share_afford, praca)))
                distratos = e.vendidas - aprovados
                self._receber(e, aprovados * e.preco_unit * 0.60)
                # distrato: devolve 50% do pago (~40% do preço) em 6 meses
                dev = distratos * e.preco_unit * 0.40 * 0.50
                for m in range(1, 7):
                    e.devolucoes_pendentes.append((t + m, dev / 6))
                e.prontas_estoque += distratos
                # quita plano empresário com o que entrou
                quit = min(e.divida_pe, e.caixa_spe if arq.afetacao else self.pool)
                e.divida_pe -= quit
                if arq.afetacao:
                    e.caixa_spe -= quit
                else:
                    self.pool -= quit

        # devoluções de distrato vencendo
        for e in self.obras:
            venc = [v for (m, v) in e.devolucoes_pendentes if m == t]
            e.devolucoes_pendentes = [(m, v) for (m, v) in e.devolucoes_pendentes if m != t]
            for v in venc:
                if not self._pagar(e, v, t):
                    self.insolvente_em = t

        # SPE entregue, sem dívida e sem devoluções pendentes distribui p/ holding
        if arq.afetacao:
            for e in self.obras:
                quitada = e.entregue and e.divida_pe <= 1 and not e.devolucoes_pendentes
                if quitada and e.caixa_spe > 0:
                    self.pool += e.caixa_spe
                    e.caixa_spe = 0.0

        # juros da linha corporativa; amortiza se sobra caixa
        self.divida_corp *= 1 + cdi_mm + (arq.spread_pe + 2) / 100 / 12
        if self.pool > 0 and self.divida_corp > 0:
            am = min(self.pool, self.divida_corp)
            self.pool -= am
            self.divida_corp -= am

        return self._rec(t, novas=novas_unidades, vendas=vendas_mes)

    def _rec(self, t, novas, vendas):
        obras_ativas = [e for e in self.obras if e.em_obra(t)]
        rec = dict(
            pool=self.pool,
            caixa_total=self.pool + sum(e.caixa_spe for e in self.obras),
            divida_corp=self.divida_corp,
            divida_pe=sum(e.divida_pe for e in self.obras),
            n_obras=len(obras_ativas),
            estoque_proprio=sum(e.estoque for e in self.obras if not e.parada),
            lancamentos=novas,
            vendas=vendas,
            insolvente=self.insolvente_em is not None,
        )
        rec["caixa_liquido"] = rec["caixa_total"] - rec["divida_corp"]
        self.hist.append(rec)
        return rec


def share_afford_repasse(share_afford: float, praca) -> float:
    """Aprovação bancária no repasse: financiados dependem da renda vs taxa;
    investidores/à vista quase sempre aprovam."""
    f = praca.share_financiado
    # normaliza pelo share de referência para que t0 signifique ~85% de aprovação
    ref = praca.share_afford_ref or share_afford
    aprov_fin = min(1.0, 0.85 * share_afford / ref)
    return f * aprov_fin + (1 - f) * 0.97


# ---------------------------------------------------------------------------
# Arquétipos
# ---------------------------------------------------------------------------

def fluxo_dependente(preco_unit_ref: float) -> Arquetipo:
    """O que se ouve em Lajeado: obra de hoje paga com lançamento de agora."""
    return Arquetipo(
        nome="fluxo_dependente", afetacao=False,
        reserva_inicial=0.06 * preco_unit_ref * 60,
        limite_credito=0.08 * preco_unit_ref * 60,
        pe_pct=0.35, spread_pe=5.0,
        n_unidades_inicial=60, crescimento_lanc=1.30, lanc_intervalo=6,
        politica="fluxo", fator_vendas=1.30,  # equipe comercial agressiva
        custo_pct=0.58, permuta_pct=0.6,
        projetos_iniciais=((8, 48, 0.80), (20, 40, 0.92)),
        max_obras=6,
    )


def intermediaria(preco_unit_ref: float) -> Arquetipo:
    return Arquetipo(
        nome="intermediaria", afetacao=True,
        reserva_inicial=0.15 * preco_unit_ref * 60,
        limite_credito=0.10 * preco_unit_ref * 60,
        pe_pct=0.45, spread_pe=4.0,
        n_unidades_inicial=60, crescimento_lanc=1.10, lanc_intervalo=10,
        politica="fluxo", fator_vendas=1.0,
        projetos_iniciais=((12, 50, 0.70),),
        max_obras=3,
    )


def capitalizada(preco_unit_ref: float) -> Arquetipo:
    return Arquetipo(
        nome="capitalizada", afetacao=True,
        reserva_inicial=0.50 * preco_unit_ref * 60,
        limite_credito=0.30 * preco_unit_ref * 60,
        pe_pct=0.60, spread_pe=3.0,
        n_unidades_inicial=60, crescimento_lanc=1.0, lanc_intervalo=12,
        politica="prudente", fator_vendas=0.95,
        projetos_iniciais=((14, 60, 0.60),),
        max_obras=3,
    )


ARQUETIPOS = {
    "fluxo_dependente": fluxo_dependente,
    "intermediaria": intermediaria,
    "capitalizada": capitalizada,
}
