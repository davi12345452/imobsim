"""Fontes de dados públicas: SGS (BCB) e Focus (BCB), com snapshot offline.

Duas camadas:
  1. snapshot em `imobsim/dados/` (commitado; o pacote roda sem rede)
  2. cache do usuário (`$IMOBSIM_CACHE` ou ~/.cache/imobsim) para datas
     que o snapshot não cobre

Séries SGS usadas (id -> coluna):
    4189   selic     Selic acumulada no mês, anualizada (% a.a.)
    192    incc_mm   INCC-DI, variação mensal (%)
    433    ipca_mm   IPCA, variação mensal (%)
    20774  taxa_fin  taxa média PF, financiamento imobiliário com taxas
                     reguladas (% a.a.); começa em mar/2011

Focus: ExpectativasMercadoAnuais (mediana e desvio-padrão por ano-calendário)
para Selic e IPCA, na última divulgação <= data pedida.

Atualizar o snapshot:  python -m imobsim.fontes
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.parse
import urllib.request

import pandas as pd

SGS_SERIES = {"selic": 4189, "incc_mm": 192, "ipca_mm": 433, "taxa_fin": 20774}
SGS_INICIO = "1994-07"  # Plano Real
_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{id}/dados"
SAFE = "',"  # OData: aspas e vírgulas ficam literais na query
_FOCUS_URL = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
              "ExpectativasMercadoAnuais")

DADOS = pathlib.Path(__file__).parent / "dados"
SNAPSHOT_SGS = DADOS / "sgs.csv"
SNAPSHOT_FOCUS = DADOS / "focus.csv"


def _cache_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("IMOBSIM_CACHE", pathlib.Path.home() / ".cache" / "imobsim"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "imobsim/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------------------
# SGS
# ---------------------------------------------------------------------------

def baixar_sgs(inicio: str = SGS_INICIO, fim: str | None = None) -> pd.DataFrame:
    """Baixa as séries mensais do SGS. Índice: Period mensal. Colunas: SGS_SERIES."""
    ini = pd.Period(inicio, "M").to_timestamp().strftime("%d/%m/%Y")
    fimp = pd.Period(fim, "M") if fim else pd.Timestamp.today().to_period("M")
    fim_s = fimp.to_timestamp(how="end").strftime("%d/%m/%Y")
    cols = {}
    for col, sid in SGS_SERIES.items():
        url = _SGS_URL.format(id=sid) + f"?formato=json&dataInicial={ini}&dataFinal={fim_s}"
        rows = _get_json(url)
        s = pd.Series({pd.Period(pd.to_datetime(r["data"], dayfirst=True), "M"): float(r["valor"])
                       for r in rows}, dtype=float)
        cols[col] = s
    df = pd.DataFrame(cols).sort_index()
    df.index.name = "mes"
    return df


def sgs(atualizar: bool = False) -> pd.DataFrame:
    """Séries mensais do SGS: snapshot do pacote, ou download se `atualizar`."""
    if atualizar or not SNAPSHOT_SGS.exists():
        df = baixar_sgs()
        if atualizar or not SNAPSHOT_SGS.exists():
            _salvar_sgs(df, SNAPSHOT_SGS if os.access(DADOS, os.W_OK) else _cache_dir() / "sgs.csv")
        return df
    df = pd.read_csv(SNAPSHOT_SGS)
    df["mes"] = pd.PeriodIndex(df["mes"], freq="M")
    return df.set_index("mes")


def _salvar_sgs(df: pd.DataFrame, path: pathlib.Path):
    out = df.copy()
    out.index = out.index.astype(str)
    out.to_csv(path, float_format="%.4f")


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------

def baixar_focus(data: str, indicador: str) -> pd.DataFrame:
    """Última divulgação Focus <= `data` para `indicador` ('Selic' | 'IPCA').

    Colunas: data (divulgação efetivamente usada), indicador, ano, mediana, desvio."""
    filtro = (f"Indicador eq '{indicador}' and Data le '{data}' and baseCalculo eq 0")
    params = {"$filter": filtro, "$orderby": "Data desc", "$top": "40", "$format": "json",
              "$select": "Data,Indicador,DataReferencia,Mediana,DesvioPadrao"}
    q = "&".join(f"{k}={urllib.parse.quote(v, safe=SAFE)}" for k, v in params.items())
    rows = _get_json(f"{_FOCUS_URL}?{q}")["value"]
    if not rows:
        raise ValueError(f"Focus sem dados para {indicador} até {data}")
    ultima = max(r["Data"] for r in rows)
    df = pd.DataFrame([r for r in rows if r["Data"] == ultima])
    df = df.rename(columns={"Data": "data", "Indicador": "indicador", "DataReferencia": "ano",
                            "Mediana": "mediana", "DesvioPadrao": "desvio"})
    df["ano"] = df["ano"].astype(int)
    return df[["data", "indicador", "ano", "mediana", "desvio"]].sort_values("ano")


def focus(data: str, indicador: str, atualizar: bool = False) -> pd.DataFrame:
    """Expectativas Focus na última divulgação <= `data`, com snapshot + cache.

    O snapshot guarda a divulgação usada, então pedir uma data entre duas
    divulgações resolve offline se a anterior já estiver salva."""
    fontes = [SNAPSHOT_FOCUS, _cache_dir() / "focus.csv"]
    if not atualizar:
        for f in fontes:
            if f.exists():
                df = pd.read_csv(f)
                cand = df[(df["indicador"] == indicador) & (df["data"] <= data)]
                if not cand.empty:
                    ultima = cand["data"].max()
                    # só aceita se a divulgação salva é recente o bastante (<= 10 dias antes)
                    if (pd.Timestamp(data) - pd.Timestamp(ultima)).days <= 10:
                        sel = cand[cand["data"] == ultima].sort_values("ano")
                        return sel.reset_index(drop=True)
    novo = baixar_focus(data, indicador)
    alvo = SNAPSHOT_FOCUS if os.access(DADOS, os.W_OK) else fontes[1]
    antigo = pd.read_csv(alvo) if alvo.exists() else pd.DataFrame(columns=novo.columns)
    junto = pd.concat([antigo, novo]).drop_duplicates(["data", "indicador", "ano"])
    junto.sort_values(["indicador", "data", "ano"]).to_csv(alvo, index=False)
    return novo.reset_index(drop=True)


def atualizar_snapshot(data_focus: str | None = None):
    """Rebaixa SGS completo e Focus (Selic e IPCA) para `data_focus` (default: hoje)."""
    df = baixar_sgs()
    _salvar_sgs(df, SNAPSHOT_SGS)
    print(f"SGS: {len(df)} meses, {df.index[0]} a {df.index[-1]} -> {SNAPSHOT_SGS}")
    data_focus = data_focus or pd.Timestamp.today().strftime("%Y-%m-%d")
    for ind in ("Selic", "IPCA"):
        f = focus(data_focus, ind, atualizar=True)
        print(f"Focus {ind} ({f['data'].iloc[0]}): "
              + ", ".join(f"{a}={m}" for a, m in zip(f["ano"], f["mediana"])))


if __name__ == "__main__":
    import sys
    atualizar_snapshot(sys.argv[1] if len(sys.argv) > 1 else None)
