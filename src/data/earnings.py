"""
Historial de resultados trimestrales: BPA real vs. estimado (sorpresa) y hora del anuncio.

Fuente principal: Yahoo (`get_earnings_dates`, ~100 trimestres, desde ~2002, sin límite diario).
Respaldo: Alpha Vantage `EARNINGS` (gratis, pero 25 peticiones/día).

Regla anti-fuga (H2, DECISIONS.md): un anuncio antes de las 12:00 hora de Nueva York se
conoce al cierre de ese día; uno posterior, al cierre del día hábil siguiente.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

COLUMNS = ["announced", "available", "estimate", "reported", "surprise_pct", "source"]


def _available(announced: pd.Series) -> pd.Series:
    """Primer cierre (fecha, UTC 00:00) en el que el resultado ya es público."""
    ny = announced.dt.tz_convert("America/New_York")
    day = ny.dt.tz_localize(None).dt.normalize()
    after_noon = ny.dt.hour >= 12
    nxt = day + pd.offsets.BDay(1)
    return pd.Series(nxt.where(after_noon, day), index=announced.index).dt.tz_localize("UTC")


def fetch_yahoo(symbol: str, limit: int = 100) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.Ticker(symbol.replace(".", "-")).get_earnings_dates(limit=limit)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = raw.rename(columns={"EPS Estimate": "estimate", "Reported EPS": "reported",
                             "Surprise(%)": "surprise_pct"})
    df = df.dropna(subset=["estimate", "reported"]).reset_index()
    df = df.rename(columns={df.columns[0]: "announced"})
    df["announced"] = pd.to_datetime(df["announced"], utc=True)
    df["available"] = _available(df["announced"])
    df["source"] = "yahoo"
    return df[COLUMNS].sort_values("announced").reset_index(drop=True)


def fetch_alpha_vantage(symbol: str, api_key: str | None = None) -> pd.DataFrame:
    api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")
    r = requests.get("https://www.alphavantage.co/query",
                     params={"function": "EARNINGS", "symbol": symbol, "apikey": api_key}, timeout=30)
    data = r.json()
    if "quarterlyEarnings" not in data:
        raise RuntimeError(data.get("Note") or data.get("Information") or str(data)[:200])
    rows = []
    for q in data["quarterlyEarnings"]:
        try:
            est, rep = float(q["estimatedEPS"]), float(q["reportedEPS"])
        except (TypeError, ValueError):
            continue
        hour = "08:00" if q.get("reportTime") == "pre-market" else "16:30"
        rows.append({"announced": pd.Timestamp(f"{q['reportedDate']} {hour}", tz="America/New_York"),
                     "estimate": est, "reported": rep,
                     "surprise_pct": float(q["surprisePercentage"]) if q.get("surprisePercentage") not in (None, "None") else None})
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    df["announced"] = df["announced"].dt.tz_convert("UTC")
    df["available"] = _available(df["announced"])
    df["source"] = "alpha_vantage"
    return df[COLUMNS].sort_values("announced").reset_index(drop=True)


def download_earnings(symbols: list[str], cache_dir: Path, max_age_days: int = 7,
                      progress=print, pause: float = 0.5) -> dict[str, str]:
    """Guarda cache_dir/{SYM}.parquet. Devuelve {símbolo: error}."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}
    for i, sym in enumerate(symbols, 1):
        path = cache_dir / f"{sym}.parquet"
        if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
            continue
        try:
            df = fetch_yahoo(sym)
            if df.empty:
                raise RuntimeError("Yahoo no devuelve historial")
            df.to_parquet(path)
            progress(f"[{i:3d}/{len(symbols)}] {sym}: {len(df)} trimestres desde {df['announced'].min().date()}")
        except Exception as exc:
            errors[sym] = str(exc)
            progress(f"[{i:3d}/{len(symbols)}] {sym}: ERROR {exc}")
        time.sleep(pause)
    return errors


def load_earnings(cache_dir: Path, symbol: str) -> pd.DataFrame | None:
    path = Path(cache_dir) / f"{symbol}.parquet"
    return pd.read_parquet(path) if path.exists() else None


def surprise_score(earn: pd.DataFrame, dates: pd.DatetimeIndex, valid_days: int = 63) -> pd.Series:
    """Sorpresa (%) del último resultado público en cada fecha, si tiene como mucho
    `valid_days` sesiones de antigüedad; si no, NaN."""
    out = pd.Series(float("nan"), index=dates)
    if earn is None or earn.empty:
        return out
    e = earn.dropna(subset=["surprise_pct"]).sort_values("available")
    pos = dates.searchsorted(pd.DatetimeIndex(e["available"]), side="left")
    for p, val in zip(pos, e["surprise_pct"].values):
        if p < len(dates):
            out.iloc[p:p + valid_days] = val          # el siguiente anuncio sobrescribe
    return out
