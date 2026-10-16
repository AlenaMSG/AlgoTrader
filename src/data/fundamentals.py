"""
Fundamentales point-in-time desde SEC EDGAR (gratis, sin API key).

    data.sec.gov/api/xbrl/companyfacts/CIK##########.json

Cada dato XBRL lleva su fecha de presentación (`filed`), así que se puede saber qué
cifra era pública en cada fecha. Regla anti-fuga: un dato presentado el día F solo
se usa a partir de F+1.

Hipótesis H1 (DECISIONS.md): calidad (beneficio bruto / activos) + valor (patrimonio / capitalización).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SEC_UA = os.getenv("SEC_USER_AGENT", "AlgoTrader personal research tools@algotrader.invalid")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
REQUEST_PAUSE = 0.15            # la SEC permite 10 peticiones/s

# Solo se guardan estas etiquetas (el fichero completo pesa varios MB por empresa)
GP_TAGS      = ["GrossProfit"]
REVENUE_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "SalesRevenueGoodsNet"]
COST_TAGS    = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
                "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]
ASSET_TAGS   = ["Assets"]
EQUITY_TAGS  = ["StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
SHARES_TAGS  = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
# Costes de siniestros de seguros: su "beneficio bruto" no es comparable (aseguradoras de
# salud como UNH/ELV/CVS no los declaran como coste de ventas) → excluidas de H1.
INSURANCE_TAGS = ["PolicyholderBenefitsAndClaimsIncurredNet",
                  "PolicyholderBenefitsAndClaimsIncurredHealthCare",
                  "BenefitsLossesAndExpenses"]
COVER_SHARES = "dei:EntityCommonStockSharesOutstanding"     # acciones en circulación (portada)
KEEP_TAGS = set(GP_TAGS + REVENUE_TAGS + COST_TAGS + ASSET_TAGS + EQUITY_TAGS + SHARES_TAGS
                + INSURANCE_TAGS)
MIN_SHARES = 1e6        # por debajo, error de escala del emisor (p. ej. MCD declara millones)

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT"}
PERIOD_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A"}


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=30)
    r.raise_for_status()
    time.sleep(REQUEST_PAUSE)
    return r


# ── Descarga y caché ─────────────────────────────────────────────────────────

def slim_facts(raw: dict, cik: int) -> dict:
    """Recorta companyfacts a las etiquetas que se usan."""
    us = raw.get("facts", {}).get("us-gaap", {})
    dei = raw.get("facts", {}).get("dei", {})
    keep = {t: us[t]["units"] for t in sorted(KEEP_TAGS) if t in us}
    if "EntityCommonStockSharesOutstanding" in dei:
        keep[COVER_SHARES] = dei["EntityCommonStockSharesOutstanding"]["units"]
    return {"cik": cik, "entityName": raw.get("entityName"), "facts": keep}


def cik_map(cache_dir: Path, max_age_days: int = 30) -> dict[str, int]:
    path = Path(cache_dir) / "company_tickers.json"
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_days * 86400:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(TICKERS_URL).content)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {v["ticker"].upper().replace("-", "."): int(v["cik_str"]) for v in raw.values()}


def download_facts(symbols: list[str], cache_dir: Path, max_age_days: int = 7,
                   progress=print, ciks: dict[str, int] | None = None) -> dict[str, str]:
    """Descarga companyfacts (solo las etiquetas de KEEP_TAGS) a cache_dir/{SYM}.json.
    Devuelve {símbolo: error} con los que fallaron."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ciks = ciks or cik_map(cache_dir)
    errors: dict[str, str] = {}
    for i, sym in enumerate(symbols, 1):
        path = cache_dir / f"{sym}.json"
        if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
            continue
        cik = ciks.get(sym.upper())
        if cik is None:
            errors[sym] = "ticker sin CIK en la SEC"
            continue
        try:
            slim = slim_facts(_get(FACTS_URL.format(cik=cik)).json(), cik)
            path.write_text(json.dumps(slim), encoding="utf-8")
            progress(f"[{i:3d}/{len(symbols)}] {sym}: {len(slim['facts'])} etiquetas")
        except Exception as exc:
            errors[sym] = str(exc)
            progress(f"[{i:3d}/{len(symbols)}] {sym}: ERROR {exc}")
    return errors


def load_facts(cache_dir: Path, symbol: str) -> dict | None:
    path = Path(cache_dir) / f"{symbol}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── Series point-in-time ─────────────────────────────────────────────────────

def _facts_df(facts: dict, tags: list[str], unit: str, forms: set[str]) -> pd.DataFrame:
    rows = []
    for prio, tag in enumerate(tags):
        for f in facts.get("facts", {}).get(tag, {}).get(unit, []):
            if f.get("form") in forms:
                rows.append({"start": f.get("start"), "end": f["end"], "filed": f["filed"],
                             "accn": f["accn"], "val": float(f["val"]), "prio": prio})
    if not rows:
        return pd.DataFrame({"start": pd.Series(dtype="datetime64[ns]"), "end": pd.Series(dtype="datetime64[ns]"),
                             "filed": pd.Series(dtype="datetime64[ns]"), "accn": pd.Series(dtype=str),
                             "val": pd.Series(dtype=float)})
    df = pd.DataFrame(rows)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    # Si varias etiquetas dan el mismo dato en la misma presentación, gana la de mayor prioridad
    return df.sort_values("prio").drop_duplicates(["accn", "start", "end"]).drop(columns="prio")


def _annual(df: pd.DataFrame) -> pd.DataFrame:
    days = (df["end"] - df["start"]).dt.days
    return df[(days >= 350) & (days <= 380)]


def _asof_series(df: pd.DataFrame) -> pd.Series:
    """Valor vigente tras cada fecha de presentación: el periodo más reciente conocido
    y, para ese periodo, la presentación más reciente (recoge reexpresiones sin mirar
    al futuro). Indexado por fecha de disponibilidad = filed + 1 día."""
    if df.empty:
        return pd.Series(dtype=float)
    df = df.sort_values(["filed", "end"])
    out, best_end, best_val = {}, None, None
    for filed, g in df.groupby("filed", sort=True):
        top = g.loc[g["end"].idxmax()]
        if best_end is None or top["end"] >= best_end:
            best_end, best_val = top["end"], top["val"]
        out[filed + pd.Timedelta(days=1)] = best_val
    s = pd.Series(out).sort_index()
    s.index = s.index.tz_localize("UTC")
    return s


def gross_profit_facts(facts: dict) -> pd.DataFrame:
    """Beneficio bruto anual: etiqueta GrossProfit, o ingresos − coste de ventas de la
    misma presentación y el mismo periodo."""
    direct = _annual(_facts_df(facts, GP_TAGS, "USD", ANNUAL_FORMS))
    rev = _annual(_facts_df(facts, REVENUE_TAGS, "USD", ANNUAL_FORMS))
    cost = _annual(_facts_df(facts, COST_TAGS, "USD", ANNUAL_FORMS))
    built = rev.merge(cost, on=["accn", "start", "end", "filed"], suffixes=("_r", "_c"))
    built["val"] = built["val_r"] - built["val_c"]
    built = built[["start", "end", "filed", "accn", "val"]]
    both = pd.concat([direct.assign(p=0), built.assign(p=1)])
    return both.sort_values("p").drop_duplicates(["accn", "start", "end"]).drop(columns="p")


def is_insurer(facts: dict) -> bool:
    """True si la empresa ha declarado alguna vez costes de siniestros en un 10-K."""
    return any(not _facts_df(facts, [t], "USD", ANNUAL_FORMS).empty for t in INSURANCE_TAGS)


def pit_fundamentals(facts: dict) -> dict[str, pd.Series]:
    """Series point-in-time (índice = fecha desde la que el dato es público, UTC)."""
    return {
        "gross_profit": _asof_series(gross_profit_facts(facts)),
        "assets":       _asof_series(_facts_df(facts, ASSET_TAGS, "USD", ANNUAL_FORMS)),
        "equity":       _asof_series(_facts_df(facts, EQUITY_TAGS, "USD", PERIOD_FORMS)),
        "shares":       _shares_series(facts),
    }


def _shares_series(facts: dict) -> pd.Series:
    """Acciones del último dato publicado: las de portada (dei) si la empresa las declara;
    si no (p. ej. varias clases de acciones), las diluidas medias. Se devuelve también la
    fecha a la que se refieren (para el ajuste por splits) como atributo `ends`."""
    df = _facts_df(facts, [COVER_SHARES], "shares", PERIOD_FORMS)
    if not df.empty:
        df = df[df["val"] >= MIN_SHARES]
    if df.empty:
        df = _facts_df(facts, SHARES_TAGS, "shares", PERIOD_FORMS)
        df = df[df["val"] >= MIN_SHARES]
    if df.empty:
        s = pd.Series(dtype=float)
        s.attrs["ends"] = pd.Series(dtype="datetime64[ns]")
        return s
    df = df.sort_values(["filed", "end"])
    vals, ends, best_end, best = {}, {}, None, None
    for filed, g in df.groupby("filed", sort=True):
        top = g.loc[g["end"].idxmax()]
        if best_end is None or top["end"] >= best_end:
            best_end, best = top["end"], top["val"]
        key = filed + pd.Timedelta(days=1)
        vals[key], ends[key] = best, best_end
    s = pd.Series(vals).sort_index()
    e = pd.Series(ends).sort_index()
    s.index = s.index.tz_localize("UTC")
    e.index = s.index
    s.attrs["ends"] = e
    return s


def split_factor_after(splits: pd.Series, dates: pd.Series) -> pd.Series:
    """Producto de los ratios de split posteriores a cada fecha (F(s) en la fórmula de la
    capitalización). `splits`: índice fecha (naive), valor ratio (2.0 = 2 por 1)."""
    if splits is None or splits.empty:
        return pd.Series(1.0, index=dates.index)
    sp = splits.sort_index()
    sd = sp.index.values
    cum = sp.values[::-1].cumprod()[::-1]          # producto desde cada split hasta el final
    out = []
    for d in pd.to_datetime(dates.values):
        j = sd.searchsorted(pd.Timestamp(d).to_datetime64(), side="right")
        out.append(float(cum[j]) if j < len(cum) else 1.0)
    return pd.Series(out, index=dates.index)


def quality_value_inputs(facts: dict, close_split: pd.Series, splits: pd.Series) -> pd.DataFrame:
    """Para cada día de `close_split` (cierre ajustado SOLO por splits, índice UTC):
    gpa = beneficio bruto / activos; bm = patrimonio / capitalización.
    Capitalización = close_split[t] · acciones_publicadas · F(fin del periodo de las acciones)."""
    pit = pit_fundamentals(facts)
    idx = close_split.index
    out = pd.DataFrame(index=idx)
    for k in ("gross_profit", "assets", "equity"):
        s = pit[k]
        out[k] = s.reindex(idx, method="ffill") if not s.empty else float("nan")
    sh = pit["shares"]
    if sh.empty:
        out["mktcap"] = float("nan")
    else:
        ends = sh.attrs["ends"]
        adj = sh * split_factor_after(splits, ends).values
        out["mktcap"] = close_split * adj.reindex(idx, method="ffill")
    out["gpa"] = out["gross_profit"] / out["assets"]
    out["bm"] = out["equity"] / out["mktcap"]
    return out[["gpa", "bm"]]
