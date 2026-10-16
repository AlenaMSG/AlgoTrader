"""
Cartera teórica de HOY para una estrategia del registro (src/analysis/strategies.py).
No envía órdenes: solo escribe strategy_portfolio.json para la web.

    .\\.venv\\Scripts\\python.exe estrategia_cartera.py --strategy h1_quality_value
    .\\.venv\\Scripts\\python.exe estrategia_cartera.py --strategy h2_earnings_surprise
    .\\.venv\\Scripts\\python.exe estrategia_cartera.py --strategy h3_insider_buying

Usa las mismas reglas que backtest_fijo.py (mismo cálculo de puntuación, top N).
Cachés: data_cache/sec (7 días), data_cache/earnings (3 días), data_cache/form345 (trimestres)
y data_cache/form4_daily (un fichero por día ya cerrado).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis.strategies import BY_ID, status          # noqa: E402
from src.data.sp500 import EXCLUDED_SECTORS_H1, SP500, yahoo_ticker   # noqa: E402

OUT = ROOT / "strategy_portfolio.json"
SEC_CACHE = ROOT / "data_cache" / "sec"
EARN_CACHE = ROOT / "data_cache" / "earnings"
FORM345_CACHE = ROOT / "data_cache" / "form345"
FORM4_DAILY = ROOT / "data_cache" / "form4_daily"
TOP_N = 40

log = logging.getLogger("estrategia_cartera")


def _prices(symbols: list[str]) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Cierre ajustado solo por splits (2 años) y splits de cada símbolo."""
    import yfinance as yf
    tickers = [yahoo_ticker(s) for s in symbols]
    raw = yf.download(tickers, period="2y", auto_adjust=False, actions=True,
                      group_by="column", progress=False, threads=True)
    close = raw["Close"].rename(columns=lambda t: t.replace("-", "."))
    close.index = pd.to_datetime(close.index, utc=True)
    splits = {}
    if "Stock Splits" in raw:
        sp = raw["Stock Splits"].rename(columns=lambda t: t.replace("-", "."))
        for s in sp.columns:
            x = sp[s][sp[s] > 0]
            x.index = pd.to_datetime(x.index).tz_localize(None).normalize()
            splits[s] = x
    return close, splits


def _cache_sin_seguros() -> bool:
    """La caché anterior al 2026-10-15 no guardaba las etiquetas de seguros: hay que renovarla."""
    f = SEC_CACHE / "UNH.json"
    return f.exists() and "PolicyholderBenefitsAndClaimsIncurredNet" not in f.read_text(encoding="utf-8")


def portfolio_h1() -> list[dict]:
    from src.data.fundamentals import download_facts, is_insurer, load_facts, quality_value_inputs
    eligible = [s for s, (sector, _, _) in SP500.items() if sector not in EXCLUDED_SECTORS_H1]
    download_facts(eligible, SEC_CACHE, ciks={s: SP500[s][1] for s in eligible}, progress=log.info,
                   max_age_days=0 if _cache_sin_seguros() else 7)
    close, splits = _prices(eligible)
    rows = []
    for s in eligible:
        facts = load_facts(SEC_CACHE, s)
        if facts is None or s not in close or close[s].dropna().empty or is_insurer(facts):
            continue
        qv = quality_value_inputs(facts, close[s].dropna(), splits.get(s, pd.Series(dtype=float)))
        last = qv.iloc[-1]
        if pd.notna(last["gpa"]) and pd.notna(last["bm"]) and last["bm"] > 0:
            rows.append({"symbol": s, "gpa": float(last["gpa"]), "bm": float(last["bm"]),
                         "precio": float(close[s].dropna().iloc[-1])})
    df = pd.DataFrame(rows)
    df["score"] = df["gpa"].rank(pct=True) + df["bm"].rank(pct=True)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["elegibles"] = len(df)
    return df.head(TOP_N).to_dict("records")


def portfolio_h2() -> list[dict]:
    from src.data.earnings import download_earnings, load_earnings, surprise_score
    syms = list(SP500)
    download_earnings(syms, EARN_CACHE, max_age_days=3, progress=log.info, pause=0.3)
    close, _ = _prices(syms)
    rows = []
    for s in syms:
        e = load_earnings(EARN_CACHE, s)
        if e is None or s not in close or close[s].dropna().empty:
            continue
        sc = surprise_score(e, close[s].dropna().index)
        if pd.notna(sc.iloc[-1]):
            last = e.dropna(subset=["surprise_pct"]).sort_values("available").iloc[-1]
            rows.append({"symbol": s, "score": float(sc.iloc[-1]),
                         "anuncio": str(last["announced"].date()),
                         "precio": float(close[s].dropna().iloc[-1])})
    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    df["elegibles"] = len(df)
    return df.head(TOP_N).to_dict("records")


def portfolio_h3() -> list[dict]:
    """Histórico: snapshot congelado del backtest (hasta su último trimestre) + trimestres
    publicados después + Form 4 diarias desde el fin del último trimestre publicado."""
    from backtest_fijo import FORM4_DIR, FORM4_UNTIL
    from src.data.insiders import (WINDOW, download_quarters, fetch_recent, insider_score,
                                   opportunistic_purchases, quarter_urls)
    ciks = {int(v[1]) for v in SP500.values()}
    parts = []
    if (FORM4_DIR / "trades.parquet").exists():
        parts.append(pd.read_parquet(FORM4_DIR / "trades.parquet"))
        after = FORM4_UNTIL
    else:
        after = None
    newer = download_quarters(ciks, FORM345_CACHE, after=after, progress=log.info)
    if not newer.empty:
        parts.append(newer)
    last_q = max(quarter_urls())                                     # p. ej. '2026q3'
    y, q = int(last_q[:4]), int(last_q[-1])
    q_end = pd.Timestamp(year=y, month=3 * q, day=1) + pd.offsets.MonthEnd(0)
    recent = fetch_recent(ciks, q_end + pd.Timedelta(days=1), progress=log.info, cache_dir=FORM4_DAILY)
    if not recent.empty:
        parts.append(recent)
    trades = pd.concat(parts, ignore_index=True)
    buys = opportunistic_purchases(trades)

    syms = list(SP500)
    close, _ = _prices(syms)
    dates = close.index
    by_cik = {int(SP500[s][1]): s for s in syms}
    since = dates[-min(WINDOW, len(dates))].tz_localize(None).normalize()
    rows = []
    for cik, g in buys.groupby("issuer_cik"):
        s = by_cik.get(int(cik))
        if s is None or s not in close or close[s].dropna().empty:
            continue
        sc = insider_score(g, dates)
        if sc.iloc[-1] <= 0:
            continue
        live = g[g["available"] >= since]
        rows.append({"symbol": s, "score": float(sc.iloc[-1]), "directivos": int(sc.iloc[-1]),
                     "importe": float(live["value"].sum()),
                     "ultima_compra": str(live["trans_date"].max().date()),
                     "precio": float(close[s].dropna().iloc[-1])})
    if not rows:
        return []
    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    df["elegibles"] = len(df)
    return df.head(TOP_N).to_dict("records")


BUILDERS = {"h1_quality_value": portfolio_h1, "h2_earnings_surprise": portfolio_h2,
            "h3_insider_buying": portfolio_h3}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=list(BUILDERS), required=True)
    args = ap.parse_args()

    top = BUILDERS[args.strategy]()
    for r in top:
        r["nombre"] = SP500[r["symbol"]][2]
        r["sector"] = SP500[r["symbol"]][0]
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    data[args.strategy] = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "estado": status(args.strategy),
        "nombre": BY_ID[args.strategy].nombre,
        "elegibles": int(top[0]["elegibles"]) if top else 0,
        "cartera": top,
    }
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"{len(top)} valores guardados en {OUT}")


if __name__ == "__main__":
    main()
