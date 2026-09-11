"""
scan_logger: registro persistente de señales en scan_log.csv.

Módulo compartido entre el scanner automático (scan_sp100.py) y los análisis
manuales de la Pestaña Análisis, para que ambos queden en el mismo historial
y sea posible comparar resultados entre modelos y fuentes de datos distintos.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

LOG_FIELDS = [
    "timestamp", "symbol", "signal", "pred_return_pct", "dir_acc_pct",
    "ask", "bid", "sentiment_score", "pc_ratio", "model_type", "data_source",
]


def _migrate_if_needed(log_path: Path) -> None:
    """Si el CSV existe pero es de antes de añadir model_type/data_source,
    reescribe el fichero añadiendo esas columnas vacías a las filas antiguas."""
    if not log_path.exists():
        return
    with log_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        if all(field in existing_fields for field in LOG_FIELDS):
            return
        rows = list(reader)

    for row in rows:
        for field in LOG_FIELDS:
            row.setdefault(field, "")

    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def append_scan_log(base_dir: Path, results: list[dict]) -> int:
    """
    Añade a scan_log.csv una fila por cada resultado con señal no NEUTRAL.
    `results` son dicts con la forma que devuelve TradingBot.run_symbol
    (symbol, signal, pred_return, metrics, quote, sentiment, options).
    Registra también el modelo y la fuente de datos activos en settings.json
    en el momento del análisis. Devuelve el número de filas añadidas.
    """
    signals = [r for r in results if r.get("signal") != "NEUTRAL"]
    if not signals:
        return 0

    from src.config.settings_manager import settings as settings_manager

    cfg         = settings_manager.load()
    model_type  = cfg.get("model_type",  "xgb_lgb_ensemble")
    data_source = cfg.get("data_source", "yahoo")

    log_path  = base_dir / "scan_log.csv"
    _migrate_if_needed(log_path)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in signals:
        m     = r.get("metrics", {})
        quote = r.get("quote", {})
        rows.append({
            "timestamp":       timestamp,
            "symbol":          r["symbol"],
            "signal":          r["signal"],
            "pred_return_pct": f"{r.get('pred_return', 0) * 100:+.2f}",
            "dir_acc_pct":     f"{m.get('oos_dir_acc', 0) * 100:.1f}",
            "ask":             f"{quote.get('ask_price', 0):.4f}",
            "bid":             f"{quote.get('bid_price', 0):.4f}",
            "sentiment_score": f"{r.get('sentiment', {}).get('sentiment_score', 0.0):+.2f}",
            "pc_ratio":        f"{r.get('options', {}).get('pc_ratio', 1.0):.2f}",
            "model_type":      model_type,
            "data_source":     data_source,
        })

    write_header = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    return len(rows)
