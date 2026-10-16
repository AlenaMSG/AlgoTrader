"""
Tests del Backtester (sin red).

Ejecutar con:
    .\\.venv\\Scripts\\python.exe tests\\test_backtester.py
(o con pytest si está instalado).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.analysis.backtester import Backtester


def _prices(opens, closes):
    idx = pd.date_range("2024-01-01", periods=len(opens), freq="B", tz="UTC")
    return pd.DataFrame({"open": opens, "high": closes, "low": opens, "close": closes, "volume": 1}, index=idx)


def test_fills_at_next_open_not_signal_close():
    # El cierre de cada día sube un 1%, pero la apertura del día siguiente ya
    # abre por encima de ese cierre (gap) y de ahí baja. Entrando al cierre del
    # día de la señal (el bug) se gana; entrando a la apertura siguiente se pierde.
    opens  = [100.0, 103.0, 102.0, 101.0, 100.0]
    closes = [101.0, 102.0, 103.0, 104.0, 105.0]
    prices = _prices(opens, closes)
    preds  = np.full(len(prices), 0.01)          # siempre señal de compra

    res = Backtester(cost_pct=0.0, buy_threshold=0.005).run(
        preds, prices["close"].to_numpy(), prices.index, prices=prices
    )
    trades = res["trades"]

    # Solo las barras con apertura t+1 y t+2 conocidas generan operación.
    assert len(trades) == 3
    t0 = trades[0]
    assert t0["entry_price"] == 103.0 and t0["exit_price"] == 102.0
    assert all(t["return_net"] < 0 for t in trades)


def test_no_trade_without_signal_and_costs_applied():
    opens  = [100.0, 100.0, 110.0, 110.0]
    closes = [100.0, 100.0, 110.0, 110.0]
    prices = _prices(opens, closes)
    preds  = np.array([0.01, 0.0, 0.0, 0.0])      # solo la primera barra compra

    res = Backtester(cost_pct=0.0005, buy_threshold=0.005).run(
        preds, prices["close"].to_numpy(), prices.index, prices=prices
    )
    assert len(res["trades"]) == 1
    expected = (110.0 * (1 - 0.0005) - 100.0 * (1 + 0.0005)) / (100.0 * (1 + 0.0005))
    assert abs(res["trades"][0]["return_net"] - expected) < 1e-12


def test_oos_index_not_contiguous():
    # Los folds del CV no tienen por qué ser contiguos: las aperturas se buscan
    # por fecha en la serie completa, no en la posición dentro del OOS.
    opens  = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    prices = _prices(opens, opens)
    oos    = prices.index[[0, 3]]
    res = Backtester(cost_pct=0.0, buy_threshold=0.005).run(
        np.array([0.01, 0.01]), prices.loc[oos, "close"].to_numpy(), oos, prices=prices
    )
    assert [(t["entry_price"], t["exit_price"]) for t in res["trades"]] == [(101.0, 102.0), (104.0, 105.0)]


if __name__ == "__main__":
    ok = True
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                ok = False
                print(f"FAIL  {name}: {exc!r}")
    sys.exit(0 if ok else 1)
