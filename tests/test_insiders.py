r"""
Tests anti-fuga de la señal de compras de directivos (H3), sin red.

Ejecutar con:
    .\.venv\Scripts\python.exe tests\test_insiders.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.data.insiders import insider_score, opportunistic_purchases


def _t(owner, trans, filed, code="P", issuer=1, shares=100.0, price=10.0, acc=None):
    return {"accession": acc or f"{owner}-{trans}-{code}", "filed": pd.Timestamp(filed), "issuer_cik": issuer,
            "owner_cik": owner, "trans_date": pd.Timestamp(trans), "code": code, "shares": shares, "price": price}


def test_rutinaria_si_opero_ese_mes_3_anios():
    tr = pd.DataFrame([
        _t(7, "2021-03-10", "2021-03-11", "S"), _t(7, "2022-03-10", "2022-03-11", "S"),
        _t(7, "2023-03-10", "2023-03-11", "P"),
        _t(7, "2024-03-12", "2024-03-13", "P"),                 # rutinaria (marzo en 2021-2023)
        _t(7, "2024-06-12", "2024-06-13", "P"),                 # oportunista (junio)
        _t(8, "2024-03-12", "2024-03-13", "P"),                 # sin historial → oportunista
    ])
    b = opportunistic_purchases(tr)
    got = set(zip(b["owner_cik"], b["trans_date"].dt.strftime("%Y-%m-%d")))
    assert (7, "2024-03-12") not in got
    assert {(7, "2024-06-12"), (8, "2024-03-12")} <= got


def test_ventas_y_precio_cero_no_puntuan():
    tr = pd.DataFrame([_t(1, "2024-05-01", "2024-05-02", "S"), _t(2, "2024-05-01", "2024-05-02", price=0.0)])
    assert opportunistic_purchases(tr).empty


def test_se_conoce_al_dia_habil_siguiente_y_caduca():
    tr = pd.DataFrame([_t(1, "2024-05-01", "2024-05-03"),   # presentada el viernes 3 → se conoce el lunes 6
                       _t(2, "2024-05-02", "2024-05-03")])
    b = opportunistic_purchases(tr)
    dates = pd.bdate_range("2024-04-29", periods=40, tz="UTC") + pd.Timedelta(hours=4)
    s = insider_score(b, dates)
    i = list(dates.normalize().tz_localize(None)).index(pd.Timestamp("2024-05-06"))
    assert s.iloc[i - 1] == 0                                # viernes: aún no se conoce
    assert int(s.iloc[i]) == 2                               # lunes: 2 directivos distintos
    assert int(s.iloc[i + 20]) == 2 and s.iloc[i + 21] == 0  # 21 sesiones y caduca


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"\n{len(tests)} tests pasados")
