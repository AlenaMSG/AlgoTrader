"""
Scanner headless del S&P100 — sin GUI, pensado para Task Scheduler o cron.

Uso:
    .venv/Scripts/python.exe scan_sp100.py

Requiere en .env:
    ALPACA_API_KEY=...
    ALPACA_SECRET_KEY=...

Opcional (para alerta Telegram):
    TELEGRAM_TOKEN=...
    TELEGRAM_CHAT_ID=...
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.config.config_manager import ConfigManager
from src.data.data_loader import DataLoader
from src.data.sp100 import SP100_SYMBOLS
from src.analysis.trading_bot import TradingBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

START_DATE = "2010-01-01"


def run_scan() -> tuple[list[dict], list[tuple[str, str]]]:
    cfg = ConfigManager()
    if not cfg.has_valid_config():
        log.error(
            "Credenciales de Alpaca no configuradas. "
            "Añade ALPACA_API_KEY y ALPACA_SECRET_KEY al .env"
        )
        sys.exit(1)

    api_key, secret_key = cfg.get_credentials()
    loader = DataLoader(api_key, secret_key, cache_dir=PROJECT_ROOT / "data_cache")
    bot    = TradingBot(loader, model_dir=PROJECT_ROOT / "models")

    log.info(f"Iniciando scan de {len(SP100_SYMBOLS)} símbolos del S&P100…")
    signals: list[dict] = []
    errors:  list[tuple[str, str]] = []

    for i, symbol in enumerate(SP100_SYMBOLS, 1):
        try:
            log.info(f"[{i:3d}/{len(SP100_SYMBOLS)}] {symbol}…")
            r = bot.run_symbol(symbol, start_date=START_DATE)
            if r["signal"] != "NEUTRAL":
                signals.append(r)
                log.info(
                    f"           → {r['signal']:25s}  "
                    f"ret={r['pred_return']*100:+.2f}%  "
                    f"DA={r['metrics'].get('oos_dir_acc', 0)*100:.0f}%"
                )
        except Exception as exc:
            log.warning(f"           → ERROR: {exc}")
            errors.append((symbol, str(exc)))

    log.info(
        f"\nScan completado — {len(signals)} señales, "
        f"{len(errors)} errores de {len(SP100_SYMBOLS)} símbolos"
    )
    return signals, errors


def export_csv(signals: list[dict]) -> None:
    if not signals:
        log.info("Sin señales — scan_log.csv no actualizado")
        return
    log_path  = PROJECT_ROOT / "scan_log.csv"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in signals:
        m = r["metrics"]
        rows.append({
            "timestamp":       timestamp,
            "symbol":          r["symbol"],
            "signal":          r["signal"],
            "pred_return_pct": f"{r['pred_return']*100:+.2f}",
            "dir_acc_pct":     f"{m.get('oos_dir_acc', 0)*100:.1f}",
            "ask":             f"{r['quote']['ask_price']:.4f}",
            "bid":             f"{r['quote']['bid_price']:.4f}",
            "sentiment_score": f"{r.get('sentiment', {}).get('sentiment_score', 0.0):+.2f}",
            "pc_ratio":        f"{r.get('options', {}).get('pc_ratio', 1.0):.2f}",
        })
    fieldnames   = list(rows[0].keys())
    write_header = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    log.info(f"scan_log.csv actualizado — {len(rows)} entradas ({log_path})")


def send_telegram(signals: list[dict], errors: list[tuple[str, str]]) -> None:
    token   = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.info("Telegram no configurado (sin TELEGRAM_TOKEN/TELEGRAM_CHAT_ID en .env)")
        return

    from src.notifications.telegram_notifier import send_alert

    strong = [r for r in signals if r["signal"] in ("COMPRAR", "VENDER")]
    weak   = [r for r in signals if "débil" in r["signal"]]

    lines = [
        f"🔍 <b>AlgoTrader — Scan S&P100</b>  "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ]

    if strong:
        lines.append(f"\n<b>{len(strong)} señales fuertes:</b>")
        for r in strong[:10]:
            icon = "✅" if "COMPRAR" in r["signal"] else "🔴"
            ret  = r["pred_return"] * 100
            da   = r["metrics"].get("oos_dir_acc", 0) * 100
            ask  = r["quote"]["ask_price"]
            lines.append(
                f"• <b>{r['symbol']}</b> {icon} {r['signal']}  "
                f"{ret:+.2f}%  DA={da:.0f}%  Ask=${ask:.2f}"
            )
        if len(strong) > 10:
            lines.append(f"  … y {len(strong) - 10} más")
    else:
        lines.append("\nSin señales fuertes esta sesión.")

    if weak:
        syms = ", ".join(r["symbol"] for r in weak[:8])
        lines.append(f"\n<i>Débiles ({len(weak)}): {syms}</i>")

    if errors:
        lines.append(f"\n<i>⚠️ {len(errors)} símbolos con error</i>")

    ok = send_alert(token, chat_id, "\n".join(lines))
    log.info(f"Telegram: {'mensaje enviado' if ok else 'error al enviar'}")


if __name__ == "__main__":
    signals, errors = run_scan()
    export_csv(signals)
    send_telegram(signals, errors)
