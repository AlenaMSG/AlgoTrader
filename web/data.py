"""
Capa de datos para el dashboard web. Reutiliza src/ sin modificarla.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # AlgoTrader/


# ── Account ──────────────────────────────────────────────────────────────────

def get_account_summary() -> dict:
    try:
        from src.config.config_manager import ConfigManager
        from src.trading.order_executor import OrderExecutor

        cfg = ConfigManager()
        api_key, secret_key = cfg.get_credentials()
        executor = OrderExecutor(api_key, secret_key, cfg.get_base_url())
        account = executor.get_account()

        today = date.today().strftime("%Y-%m-%d")
        week_ago = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        try:
            pnl = executor.get_portfolio_pnl(week_ago, today)
        except Exception:
            pnl = {"pnl": 0.0, "pnl_pct": 0.0}

        return {**account, **pnl, "error": None}
    except Exception as exc:
        return {
            "error": str(exc),
            "portfolio_value": 0,
            "cash": 0,
            "buying_power": 0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
        }


def get_positions() -> list[dict]:
    try:
        from src.config.config_manager import ConfigManager
        from src.trading.order_executor import OrderExecutor

        cfg = ConfigManager()
        api_key, secret_key = cfg.get_credentials()
        executor = OrderExecutor(api_key, secret_key, cfg.get_base_url())
        positions = executor.api.list_positions()
        symbols   = [p.symbol for p in positions]

        # Fecha de la última compra ejecutada de cada símbolo (para "Fecha compra")
        entry_dates: dict[str, str] = {}
        if symbols:
            try:
                buy_orders = executor.api.list_orders(
                    status="closed", symbols=symbols, side="buy",
                    limit=500, direction="desc",
                )
                for o in buy_orders:
                    if o.symbol not in entry_dates and o.filled_at is not None:
                        entry_dates[o.symbol] = o.filled_at.strftime("%d-%m-%Y")
            except Exception:
                pass

        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,
                "side": p.side,
                "entry_date": entry_dates.get(p.symbol, "—"),
            }
            for p in positions
        ]
    except Exception:
        return []


def sell_position(symbol: str, qty: float | None = None) -> dict:
    """Vende `qty` acciones de symbol (o toda la posición si qty es None)."""
    try:
        from src.config.config_manager import ConfigManager
        from src.data.data_fetcher import DataFetcher
        from src.trading.order_executor import OrderExecutor

        cfg = ConfigManager()
        api_key, secret_key = cfg.get_credentials()
        executor = OrderExecutor(api_key, secret_key, cfg.get_base_url())
        quote = DataFetcher(api_key, secret_key).get_quote(symbol)
        return executor.close_position(symbol, quote, qty)
    except Exception as exc:
        return {"action": "error", "reason": str(exc), "order": None}


def get_portfolio_history(period: str = "1M") -> dict:
    """Retorna timestamps + equity para equity curve."""
    try:
        from src.config.config_manager import ConfigManager
        from src.trading.order_executor import OrderExecutor

        cfg = ConfigManager()
        api_key, secret_key = cfg.get_credentials()
        executor = OrderExecutor(api_key, secret_key, cfg.get_base_url())
        hist = executor.api.get_portfolio_history(timeframe="1D", period=period)
        return {
            "timestamps": hist.timestamp,
            "equity": hist.equity,
            "profit_loss": hist.profit_loss,
        }
    except Exception:
        return {"timestamps": [], "equity": [], "profit_loss": []}


# ── Signals ───────────────────────────────────────────────────────────────────

def get_pending_signals() -> dict:
    path = ROOT / "pending_signals.json"
    if not path.exists():
        return {"scan_timestamp": "—", "signals": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"scan_timestamp": "—", "signals": []}


# ── Logs ─────────────────────────────────────────────────────────────────────

def get_scan_log() -> list[dict]:
    import pandas as pd
    path = ROOT / "scan_log.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
        return df.to_dict("records")
    except Exception:
        return []


def get_orders_log() -> list[dict]:
    import pandas as pd
    path = ROOT / "orders_log.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
        return df.to_dict("records")
    except Exception:
        return []


def get_predictions_log() -> list[dict]:
    import pandas as pd
    path = ROOT / "predictions_log.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
        return df.to_dict("records")
    except Exception:
        return []


# ── Market data ──────────────────────────────────────────────────────────────

def get_candlestick_data(symbol: str, period: str = "6mo", interval: str = "1d") -> dict:
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            return {"error": f"Sin datos para {symbol}"}
        df = df.dropna()
        return {
            "dates": df.index.strftime("%Y-%m-%d").tolist(),
            "open": df["Open"].squeeze().tolist(),
            "high": df["High"].squeeze().tolist(),
            "low": df["Low"].squeeze().tolist(),
            "close": df["Close"].squeeze().tolist(),
            "volume": df["Volume"].squeeze().tolist(),
            "error": None,
        }
    except Exception as exc:
        return {"error": str(exc)}
