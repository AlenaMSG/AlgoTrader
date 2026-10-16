"""
Tests anti-fuga de fundamentales SEC y resultados trimestrales (sin red).

Ejecutar con:
    .\\.venv\\Scripts\\python.exe tests\\test_fundamentals.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.data.earnings import _available, surprise_score
from src.data.fundamentals import pit_fundamentals, quality_value_inputs, split_factor_after


def _fact(start, end, filed, val, form="10-K", accn=None):
    f = {"end": end, "filed": filed, "val": val, "form": form, "accn": accn or f"acc-{filed}-{end}"}
    if start:
        f["start"] = start
    return f


FACTS = {"facts": {
    # FY2020 publicado el 2021-02-15 (100); el 10-K de FY2021 lo reexpresa a 80 el 2022-02-15
    "GrossProfit": {"USD": [
        _fact("2020-01-01", "2020-12-31", "2021-02-15", 100.0, accn="k20"),
        _fact("2021-01-01", "2021-12-31", "2022-02-15", 150.0, accn="k21"),
        _fact("2020-01-01", "2020-12-31", "2022-02-15", 80.0, accn="k21"),
        # trimestral: no debe usarse como beneficio bruto anual
        _fact("2021-04-01", "2021-06-30", "2021-08-01", 999.0, form="10-Q", accn="q21"),
    ]},
    "Assets": {"USD": [
        _fact(None, "2020-12-31", "2021-02-15", 1000.0, accn="k20"),
        _fact(None, "2021-12-31", "2022-02-15", 1000.0, accn="k21"),
    ]},
    "StockholdersEquity": {"USD": [_fact(None, "2020-12-31", "2021-02-15", 500.0, accn="k20")]},
    "dei:EntityCommonStockSharesOutstanding": {"shares": [
        _fact(None, "2021-01-31", "2021-02-15", 10_000_000.0, accn="k20"),
    ]},
}}


def test_dato_solo_desde_el_dia_siguiente():
    gp = pit_fundamentals(FACTS)["gross_profit"]
    assert pd.Timestamp("2021-02-15", tz="UTC") not in gp.index
    assert gp.index[0] == pd.Timestamp("2021-02-16", tz="UTC")
    idx = pd.date_range("2021-02-12", "2021-02-17", freq="D", tz="UTC")
    s = gp.reindex(idx, method="ffill")
    assert pd.isna(s[pd.Timestamp("2021-02-15", tz="UTC")])     # el día de presentación aún no se conoce
    assert s[pd.Timestamp("2021-02-16", tz="UTC")] == 100.0


def test_reexpresion_no_viaja_al_pasado():
    gp = pit_fundamentals(FACTS)["gross_profit"]
    # Antes de 2022-02-16 el valor vigente es 100 (el original); nunca 80 (reexpresado después)
    antes = gp[gp.index < pd.Timestamp("2022-02-16", tz="UTC")]
    assert (antes == 100.0).all() and 80.0 not in antes.values
    # Después, el periodo más reciente (FY2021 = 150)
    assert gp.iloc[-1] == 150.0
    assert 999.0 not in gp.values                                # el trimestral no cuenta


def test_split_factor():
    splits = pd.Series([2.0, 4.0], index=pd.to_datetime(["2022-01-10", "2024-06-10"]))
    dates = pd.Series(pd.to_datetime(["2021-01-31", "2023-01-01", "2025-01-01"]))
    assert split_factor_after(splits, dates).tolist() == [8.0, 4.0, 1.0]


def test_capitalizacion_con_split_posterior():
    # 10M acciones a 2021-01-31; split 2:1 en 2022 → el cierre "solo-splits" de 2021 es la mitad
    # del real (50 en vez de 100). Capitalización real = 100 · 10M = 1.000M.
    idx = pd.date_range("2021-03-01", periods=3, freq="D", tz="UTC")
    close_split = pd.Series(50.0, index=idx)
    splits = pd.Series([2.0], index=pd.to_datetime(["2022-01-10"]))
    qv = quality_value_inputs(FACTS, close_split, splits)
    assert abs(qv["bm"].iloc[-1] - 500.0 / 1_000_000_000.0) < 1e-15
    assert abs(qv["gpa"].iloc[-1] - 0.1) < 1e-12


def test_hora_del_anuncio():
    ann = pd.Series(pd.to_datetime([
        "2024-05-01 07:00", "2024-05-01 16:30", "2024-05-03 16:30",      # miércoles, miércoles, viernes
    ]).tz_localize("America/New_York").tz_convert("UTC"))
    av = _available(ann)
    assert av.iloc[0] == pd.Timestamp("2024-05-01", tz="UTC")    # antes de abrir → se conoce ese cierre
    assert av.iloc[1] == pd.Timestamp("2024-05-02", tz="UTC")    # tras el cierre → al día siguiente
    assert av.iloc[2] == pd.Timestamp("2024-05-06", tz="UTC")    # viernes tarde → lunes


def test_sorpresa_caduca():
    dates = pd.date_range("2024-01-01", periods=100, freq="B", tz="UTC") + pd.Timedelta(hours=5)
    earn = pd.DataFrame({"available": [dates[10].normalize()], "surprise_pct": [12.0]})
    s = surprise_score(earn, dates, valid_days=63)
    assert pd.isna(s.iloc[9]) and s.iloc[10] == 12.0 and s.iloc[72] == 12.0 and pd.isna(s.iloc[73])


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)} tests pasados")
