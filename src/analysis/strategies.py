"""
Registro de estrategias (hipótesis pre-registradas en DECISIONS.md) y su estado.

El estado NO se edita a mano: sale de backtest_results/historial.csv (backtest_fijo.py).
  - "Sin datos"          : falta el descargador o el snapshot de su fuente.
  - "En validación"      : aún no se ha medido en el backtest fijo.
  - "No aceptada"        : medida en desarrollo, no cumple los criterios 1-2-3, pero le quedan
                           intentos (máx. 3, cada uno con su razón escrita antes de medir).
  - "Descartada"         : agotó los 3 intentos o se cerró por decisión (`cerrada=True`).
  - "Pendiente holdout"  : cumple en desarrollo; falta la ejecución única del holdout.
  - "Aprobada"           : cumple en desarrollo y el holdout mantiene Sharpe > benchmark e IC > 0.
Solo una estrategia "Aprobada" puede enviar órdenes (can_trade).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HISTORIAL = ROOT / "backtest_results" / "historial.csv"


@dataclass(frozen=True)
class Strategy:
    id: str
    prioridad: int
    nombre: str
    resumen: str
    fuente: str
    universo: str
    rebalanceo: str
    evidencia: str
    backtest_label: str | None      # columna `variant` en historial.csv
    datos_listos: bool = True
    recomendada: bool = False
    cerrada: bool = False           # descartada definitivamente (DECISIONS.md)


STRATEGIES: list[Strategy] = [
    Strategy(
        id="h1_quality_value", prioridad=1, recomendada=True,
        nombre="H1 · Calidad + valor",
        resumen="Compra las 40 empresas no financieras con mejor combinación de rentabilidad "
                "(beneficio bruto / activos) y precio razonable (patrimonio / capitalización).",
        fuente="SEC EDGAR — balances oficiales (gratis)",
        universo="S&P 500 sin financieras ni inmobiliarias",
        rebalanceo="Cada 21 sesiones (≈ mensual), top 40 equiponderado",
        evidencia="Novy-Marx (2013): más fuerte en grandes empresas y para quien solo compra. "
                  "La prima se ha reducido en las dos últimas décadas.",
        backtest_label="h1_quality_value_v2",
    ),
    Strategy(
        id="h2_earnings_surprise", prioridad=2,
        nombre="H2 · Sorpresa en resultados",
        resumen="Compra las 40 empresas cuyo último resultado trimestral superó más lo que "
                "esperaban los analistas (válido 63 sesiones tras el anuncio).",
        fuente="Yahoo — historial de resultados (respaldo: Alpha Vantage EARNINGS)",
        universo="S&P 500",
        rebalanceo="Cada 21 sesiones (≈ mensual), top 40 equiponderado",
        evidencia="Bernard y Thomas (1989). Prior bajo: Martineau (2022) no lo encuentra en "
                  "grandes empresas desde 2006.",
        backtest_label="h2_earnings_surprise_v2",
    ),
    Strategy(
        id="h3_insider_buying", prioridad=3,
        datos_listos=(ROOT / "backtest_data" / "form4_v1" / "manifest.json").exists(),
        nombre="H3 · Compras de directivos",
        resumen="Compra las empresas en las que consejeros o directivos han comprado acciones "
                "con su propio dinero en las últimas 21 sesiones, fuera de su patrón habitual. "
                "Más directivos comprando = más arriba en la lista.",
        fuente="SEC EDGAR — Form 4 (gratis)",
        universo="S&P 500",
        rebalanceo="Cada 21 sesiones; solo valores con señal (máx. 40). Con menos de 5, se queda en el índice",
        evidencia="Cohen, Malloy y Pomorski (2012): +0,82 %/mes en compras oportunistas; "
                  "Alldredge y Blank (2019): compras de varios directivos a la vez.",
        backtest_label="h3_insider_buying_v2",
    ),
    Strategy(
        id="ml_diario", prioridad=9, cerrada=True,
        nombre="Modelo ML diario (anterior)",
        resumen="Random forest con 29 indicadores técnicos, señal diaria por acción.",
        fuente="Precios diarios (Yahoo / Alpaca)",
        universo="S&P 100",
        rebalanceo="Diario",
        evidencia="Medido el 2026-10-14: −16 % vs +403 % del benchmark, acierto 50,2 %.",
        backtest_label="base",
    ),
]

BY_ID = {s.id: s for s in STRATEGIES}
DEFAULT_STRATEGY = "h1_quality_value"

ESTADO_COLOR = {
    "Aprobada": "success", "Pendiente holdout": "info", "En validación": "warning",
    "No aceptada": "warning", "Descartada": "danger", "Sin datos": "secondary",
}


def _historial() -> pd.DataFrame:
    try:
        return pd.read_csv(HISTORIAL)
    except Exception:
        return pd.DataFrame()


def _as_bool(v) -> bool:
    return str(v).strip().lower() == "true"


def results(strategy_id: str) -> dict:
    """Última medición en desarrollo y en holdout (filas de historial.csv) o None."""
    s = BY_ID[strategy_id]
    h = _historial()
    if h.empty or s.backtest_label is None:
        return {"desarrollo": None, "holdout": None}
    rows = h[h["variant"] == s.backtest_label]
    if strategy_id == "ml_diario":
        rows = rows[rows["model"] == "random_forest"]
    dev = rows[rows["tipo"] == "desarrollo"]
    hold = rows[rows["tipo"] == "HOLDOUT"]
    return {"desarrollo": dev.iloc[-1].to_dict() if len(dev) else None,
            "holdout": hold.iloc[-1].to_dict() if len(hold) else None}


MAX_INTENTOS = 3


def attempts(strategy_id: str) -> int:
    """Intentos medidos en desarrollo = configuraciones distintas (config_hash) de esa etiqueta."""
    s = BY_ID[strategy_id]
    h = _historial()
    if h.empty or s.backtest_label is None:
        return 0
    rows = h[(h["variant"] == s.backtest_label) & (h["tipo"] == "desarrollo")]
    return int(rows["config_hash"].nunique())


def status(strategy_id: str) -> str:
    s = BY_ID[strategy_id]
    if not s.datos_listos:
        return "Sin datos"
    r = results(strategy_id)
    dev, hold = r["desarrollo"], r["holdout"]
    if dev is None:
        return "En validación"
    if not _as_bool(dev["aceptado"]):
        return "Descartada" if s.cerrada or attempts(strategy_id) >= MAX_INTENTOS else "No aceptada"
    if hold is None:
        return "Pendiente holdout"
    ok = float(hold["sharpe"]) > float(hold["sharpe_bench"]) and float(hold["ic"]) > 0
    return "Aprobada" if ok else "Descartada"


def can_trade(strategy_id: str) -> bool:
    return strategy_id in BY_ID and status(strategy_id) == "Aprobada"
