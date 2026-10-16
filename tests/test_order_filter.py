"""
Filtro de capacidad predictiva de OrderExecutor (sin red).

Ejecutar con:
    .venv/Scripts/python.exe tests/test_order_filter.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trading.order_executor import MIN_DIR_ACCURACY, min_dir_accuracy


def test_never_accepts_coin_flip():
    for n in (0, 100, 1_500, 4_000, 1_000_000):
        assert min_dir_accuracy(n) >= MIN_DIR_ACCURACY > 0.5


def test_requires_statistical_significance():
    # 1.500 filas → 1.250 OOS → 50% + 1.96·sqrt(0.25/1250) ≈ 52.77%
    assert abs(min_dir_accuracy(1_500) - 0.52772) < 1e-4
    # Con muchos datos manda el suelo
    assert min_dir_accuracy(100_000) == MIN_DIR_ACCURACY


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
