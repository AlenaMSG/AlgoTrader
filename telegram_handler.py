"""
AlgoTrader — Telegram Bot Handler

Escucha comandos de Telegram y ejecuta órdenes en Alpaca.
Solo responde al TELEGRAM_CHAT_ID configurado en .env (seguridad).

Comandos:
  /buy SYMBOL [amount]  — comprar según señal del último scan
  /sell SYMBOL          — cerrar posición (cierre manual, sin filtros)
  /positions            — listar posiciones abiertas
  /account              — saldo y poder de compra
  /signals              — señales del último scan con comandos de ejecución
  /help                 — mostrar ayuda

Uso:
    .venv/Scripts/python.exe telegram_handler.py

Requiere en .env:
    ALPACA_API_KEY, ALPACA_SECRET_KEY (paper)
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    TRADING_MODE=paper   (o live con LIVE_* keys)
    DEFAULT_TRADE_AMOUNT=1000
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import requests

from src.config.config_manager import ConfigManager
from src.data.data_loader import DataLoader
from src.trading.order_executor import OrderExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

POLL_INTERVAL   = 5          # segundos entre polling
STATE_FILE      = PROJECT_ROOT / "telegram_handler_state.json"
SIGNALS_FILE    = PROJECT_ROOT / "pending_signals.json"


# ── Estado de offset (evita reprocesar mensajes viejos) ────────────────────

def _load_offset() -> int:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("offset", 0)
        except Exception:
            pass
    return 0


def _save_offset(offset: int) -> None:
    STATE_FILE.write_text(json.dumps({"offset": offset}), encoding="utf-8")


# ── Telegram API helpers ───────────────────────────────────────────────────

def _tg_get(token: str, method: str, params: dict) -> dict | None:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/{method}",
            params=params,
            timeout=15,
        )
        if r.ok:
            return r.json()
    except Exception as exc:
        log.warning(f"Telegram GET {method}: {exc}")
    return None


def _send(token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        log.warning(f"Telegram send error: {exc}")


# ── Carga de señales pendientes ────────────────────────────────────────────

def _load_signals() -> dict:
    if not SIGNALS_FILE.exists():
        return {}
    try:
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _find_signal(symbol: str) -> dict | None:
    data = _load_signals()
    if not data:
        return None
    scan_date = data.get("scan_timestamp", "")[:10]
    if scan_date != str(date.today()):
        return None   # señales de otro día — no usar
    for s in data.get("signals", []):
        if s["symbol"].upper() == symbol.upper():
            return s
    return None


# ── Formateo ───────────────────────────────────────────────────────────────

def _fmt_positions(positions: list[dict]) -> str:
    if not positions:
        return "Sin posiciones abiertas."
    lines = ["<b>Posiciones abiertas:</b>"]
    for p in positions:
        sign  = "+" if p["unrealized_pl"] >= 0 else ""
        pct   = p["unrealized_plpc"] * 100
        lines.append(
            f"• <b>{p['symbol']}</b> {p['side'].upper()}  "
            f"{p['qty']:.2f} acc  "
            f"entrada ${p['avg_entry_price']:.2f}  "
            f"ahora ${p['current_price']:.2f}  "
            f"P&L {sign}{p['unrealized_pl']:.2f}$ ({sign}{pct:.1f}%)"
        )
    return "\n".join(lines)


def _fmt_account(account: dict, mode: str) -> str:
    modo = "🟡 PAPER" if mode == "paper" else "🔴 LIVE"
    return (
        f"<b>Cuenta Alpaca — {modo}</b>\n"
        f"Cartera:       ${account['portfolio_value']:,.2f}\n"
        f"Efectivo:      ${account['cash']:,.2f}\n"
        f"Poder compra:  ${account['buying_power']:,.2f}"
    )


def _fmt_signals(data: dict) -> str:
    if not data or not data.get("signals"):
        return "Sin señales del último scan. Corre el scanner primero."
    ts      = data.get("scan_timestamp", "?")
    signals = data["signals"]
    strong  = [s for s in signals if s["signal"] in ("COMPRAR", "VENDER")]
    weak    = [s for s in signals if "débil" in s["signal"]]

    lines = [f"<b>Señales del scan</b>  {ts}"]
    if strong:
        lines.append(f"\n<b>Señales fuertes ({len(strong)}):</b>")
        for s in strong[:10]:
            icon = "✅" if "COMPRAR" in s["signal"] else "🔴"
            ret  = s["pred_return"] * 100
            da   = s["metrics"].get("oos_dir_acc", 0) * 100
            ask  = s["stale_quote"].get("ask_price", 0)
            cmd  = "buy" if "COMPRAR" in s["signal"] else "sell"
            lines.append(
                f"{icon} <b>{s['symbol']}</b> {ret:+.2f}%  DA={da:.0f}%  "
                f"Ask≈${ask:.2f}  →  /{cmd} {s['symbol']}"
            )
    else:
        lines.append("\nSin señales fuertes (retorno predicho &lt; ±0.5%).")

    if weak:
        syms = ", ".join(s["symbol"] for s in weak[:8])
        lines.append(f"\n<i>Débiles ({len(weak)}): {syms}</i>")

    return "\n".join(lines)


def _fmt_result(symbol: str, result: dict, mode: str) -> str:
    modo  = "PAPER" if mode == "paper" else "⚠️ LIVE"
    action = result["action"]
    reason = result["reason"]
    if action == "buy":
        return f"✅ [{modo}] COMPRA ejecutada: <b>{symbol}</b>\n{reason}"
    if action == "sell":
        return f"🔴 [{modo}] VENTA ejecutada: <b>{symbol}</b>\n{reason}"
    if action == "skip":
        return f"⏭ <b>{symbol}</b> — sin acción\n{reason}"
    return f"❌ <b>{symbol}</b> — error\n{reason}"


# ── Comandos ───────────────────────────────────────────────────────────────

def cmd_buy(parts: list[str], executor: OrderExecutor, loader: DataLoader,
            cfg: ConfigManager, token: str, chat_id: str) -> None:
    if len(parts) < 2:
        _send(token, chat_id, "Uso: /buy SYMBOL [amount]\nEjemplo: /buy AAPL 500")
        return

    symbol = parts[1].upper()
    amount = cfg.get_trade_amount()
    if len(parts) >= 3:
        try:
            amount = float(parts[2])
        except ValueError:
            _send(token, chat_id, f"❌ Monto inválido: {parts[2]}")
            return

    sig = _find_signal(symbol)
    if not sig:
        _send(token, chat_id,
              f"⚠️ No hay señal de hoy para <b>{symbol}</b>.\n"
              f"Usa /signals para ver las señales disponibles.")
        return

    if "COMPRAR" not in sig["signal"]:
        _send(token, chat_id,
              f"⚠️ La señal de hoy para {symbol} es <b>{sig['signal']}</b> "
              f"(ret {sig['pred_return']*100:+.2f}%), no de compra.\n"
              f"Si quieres comprar igualmente, el scanner no lo recomienda.")
        return

    _send(token, chat_id, f"⏳ Obteniendo cotización en tiempo real para {symbol}…")
    try:
        quote = loader.get_quote(symbol)
    except Exception as exc:
        _send(token, chat_id, f"❌ Error al obtener cotización: {exc}")
        return

    result = executor.execute_signal(
        symbol=symbol,
        signal=sig["signal"],
        pred_return=sig["pred_return"],
        quote=quote,
        metrics=sig["metrics"],
        trade_amount=amount,
        backtest_metrics=sig.get("backtest_metrics") or None,
    )
    _send(token, chat_id, _fmt_result(symbol, result, cfg.get_trading_mode()))
    log.info(f"[/buy {symbol}] → {result['action']}: {result['reason']}")


def cmd_sell(parts: list[str], executor: OrderExecutor, loader: DataLoader,
             cfg: ConfigManager, token: str, chat_id: str) -> None:
    if len(parts) < 2:
        _send(token, chat_id, "Uso: /sell SYMBOL\nEjemplo: /sell AAPL")
        return

    symbol = parts[1].upper()
    _send(token, chat_id, f"⏳ Obteniendo cotización para cerrar {symbol}…")
    try:
        quote = loader.get_quote(symbol)
    except Exception as exc:
        _send(token, chat_id, f"❌ Error al obtener cotización: {exc}")
        return

    result = executor.close_position(symbol, quote)
    _send(token, chat_id, _fmt_result(symbol, result, cfg.get_trading_mode()))
    log.info(f"[/sell {symbol}] → {result['action']}: {result['reason']}")


def cmd_positions(executor: OrderExecutor, token: str, chat_id: str) -> None:
    try:
        positions = executor.get_all_positions()
        _send(token, chat_id, _fmt_positions(positions))
    except Exception as exc:
        _send(token, chat_id, f"❌ Error al obtener posiciones: {exc}")


def cmd_account(executor: OrderExecutor, cfg: ConfigManager,
                token: str, chat_id: str) -> None:
    try:
        account = executor.get_account()
        _send(token, chat_id, _fmt_account(account, cfg.get_trading_mode()))
    except Exception as exc:
        _send(token, chat_id, f"❌ Error al obtener cuenta: {exc}")


def cmd_signals(token: str, chat_id: str) -> None:
    data = _load_signals()
    _send(token, chat_id, _fmt_signals(data))


def cmd_help(token: str, chat_id: str, cfg: ConfigManager) -> None:
    modo = "🟡 PAPER" if cfg.get_trading_mode() == "paper" else "🔴 LIVE"
    _send(token, chat_id,
          f"<b>AlgoTrader Bot — {modo}</b>\n\n"
          "/buy SYMBOL [amount] — comprar según señal del scanner\n"
          "/sell SYMBOL         — cerrar posición (manual)\n"
          "/positions           — posiciones abiertas\n"
          "/account             — saldo de la cuenta\n"
          "/signals             — señales del último scan\n"
          "/help                — esta ayuda\n\n"
          f"Monto por defecto: ${cfg.get_trade_amount():,.0f}\n"
          "Para cambiar modo paper/live: edita TRADING_MODE en .env")


# ── Loop principal ─────────────────────────────────────────────────────────

def main() -> None:
    cfg = ConfigManager()

    token   = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.error("TELEGRAM_TOKEN y TELEGRAM_CHAT_ID son obligatorios en .env")
        sys.exit(1)

    if not cfg.has_valid_config():
        log.error("Credenciales Alpaca no configuradas en .env")
        sys.exit(1)

    mode = cfg.get_trading_mode()
    api_key, secret_key = cfg.get_credentials()
    base_url = cfg.get_base_url()

    loader   = DataLoader(api_key, secret_key, cache_dir=PROJECT_ROOT / "data_cache")
    executor = OrderExecutor(api_key, secret_key, base_url=base_url)

    modo_str = "PAPER (demo)" if mode == "paper" else "⚠️  LIVE (dinero real)"
    log.info(f"AlgoTrader Handler iniciado — modo {modo_str}")
    log.info(f"Escuchando comandos en chat_id={chat_id} | polling cada {POLL_INTERVAL}s")

    _send(token, chat_id,
          f"🤖 <b>AlgoTrader Handler iniciado</b>\n"
          f"Modo: {'🟡 PAPER' if mode == 'paper' else '🔴 LIVE'}\n"
          f"Escribe /help para ver los comandos disponibles.")

    offset = _load_offset()

    while True:
        try:
            resp = _tg_get(token, "getUpdates", {"offset": offset, "timeout": 5})
            if not resp or not resp.get("ok"):
                time.sleep(POLL_INTERVAL)
                continue

            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                _save_offset(offset)

                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                # Seguridad: solo responde al chat configurado
                incoming_chat = str(msg.get("chat", {}).get("id", ""))
                if incoming_chat != str(chat_id):
                    log.warning(f"Mensaje de chat_id desconocido {incoming_chat} — ignorado")
                    continue

                text = (msg.get("text") or "").strip()
                if not text.startswith("/"):
                    continue

                parts = text.split()
                cmd   = parts[0].lower().split("@")[0]   # elimina @botname si viene

                log.info(f"Comando recibido: {text}")

                if cmd == "/buy":
                    cmd_buy(parts, executor, loader, cfg, token, chat_id)
                elif cmd == "/sell":
                    cmd_sell(parts, executor, loader, cfg, token, chat_id)
                elif cmd == "/positions":
                    cmd_positions(executor, token, chat_id)
                elif cmd == "/account":
                    cmd_account(executor, cfg, token, chat_id)
                elif cmd == "/signals":
                    cmd_signals(token, chat_id)
                elif cmd == "/help" or cmd == "/start":
                    cmd_help(token, chat_id, cfg)
                else:
                    _send(token, chat_id,
                          f"Comando no reconocido: <code>{cmd}</code>\nEscribe /help")

        except KeyboardInterrupt:
            log.info("Handler detenido por el usuario.")
            break
        except Exception as exc:
            log.warning(f"Error en loop principal: {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
