"""
Comprueba que los precios que usa el pipeline están ajustados por splits.

Para cada split conocido (tests/fixtures/splits_av.json, descargado de
Alpha Vantage SPLITS) el cierre del día del split no puede caer ≈ 1/factor
respecto al día anterior. Con Alpaca adjustment="raw" (bug nº1 de la
auditoría) NVDA 2024-06-10 aparecía como un -90%.

Necesita red y las claves de Alpaca en .env. Ejecutar con:
    .\\.venv\\Scripts\\python.exe tests\\test_split_adjustment.py
(o con pytest si está instalado).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from dotenv import load_dotenv

from src.data.data_loader import DataLoader

load_dotenv(ROOT / ".env")

SPLITS = json.loads((ROOT / "tests" / "fixtures" / "splits_av.json").read_text())["splits"]

# Un movimiento real de un día nunca se parece a 1/factor (factor ≥ 3 → caída ≥ 66%).
# Se marca como "sin ajustar" si el ratio cierre/cierre_anterior está a menos
# de un 25% de 1/factor.
_TOL = 0.25


def _unadjusted_jumps(df: pd.DataFrame, splits: list[dict]) -> list[str]:
    close = df["close"].copy()
    close.index = pd.to_datetime(close.index, utc=True).tz_convert(None).normalize()
    errors = []
    for sp in splits:
        day = pd.Timestamp(sp["date"])
        if day not in close.index:
            continue
        pos = close.index.get_loc(day)
        if pos == 0:
            continue
        ratio = close.iloc[pos] / close.iloc[pos - 1]
        expected_raw = 1.0 / sp["factor"]
        if abs(ratio / expected_raw - 1.0) < _TOL:
            errors.append(f"{sp['date']} split {sp['factor']:g}:1 -> ratio {ratio:.3f}")
    return errors


def _loader(cache_dir: str) -> DataLoader:
    return DataLoader(os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", ""), Path(cache_dir))


def _check(load_fn_name: str) -> dict[str, list[str]]:
    failures = {}
    with tempfile.TemporaryDirectory() as tmp:   # sin caché: datos frescos de la API
        dl = _loader(tmp)
        for symbol, splits in SPLITS.items():
            df = getattr(dl, load_fn_name)(symbol, start="2020-01-01")
            errs = _unadjusted_jumps(df, splits)
            if errs:
                failures[symbol] = errs
    return failures


def test_detector_catches_raw_prices():
    """El propio detector debe fallar con una serie sin ajustar."""
    idx = pd.to_datetime(["2024-06-07", "2024-06-10", "2024-06-11"])
    raw = pd.DataFrame({"close": [1208.42, 121.93, 120.92]}, index=idx)
    assert _unadjusted_jumps(raw, [{"date": "2024-06-10", "factor": 10.0}])


def test_alpaca_prices_are_split_adjusted():
    failures = _check("load_alpaca_bars")
    assert not failures, f"Alpaca sin ajustar: {failures}"


def test_yahoo_prices_are_split_adjusted():
    failures = _check("load_yfinance")
    assert not failures, f"Yahoo sin ajustar: {failures}"


if __name__ == "__main__":
    ok = True
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                ok = False
                print(f"FAIL  {name}: {exc}")
    sys.exit(0 if ok else 1)
