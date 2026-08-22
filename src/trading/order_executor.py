"""
OrderExecutor: ejecuta órdenes límite en Alpaca (paper o live).
basándose en las señales del ensemble de regresión XGBoost+LightGBM.
"""
from __future__ import annotations

import logging

import alpaca_trade_api as tradeapi

logger = logging.getLogger(__name__)

PAPER_URL              = "https://paper-api.alpaca.markets"
LIVE_URL               = "https://api.alpaca.markets"
MIN_DIR_ACCURACY       = 0.50    # umbral reducido — 52% era estructuralmente imposible con regresión
BUY_RETURN_THRESHOLD   = 0.005   # retorno mínimo predicho para COMPRAR (+0.5%)
SELL_RETURN_THRESHOLD  = -0.005  # retorno máximo predicho para VENDER (-0.5%)
KELLY_FRACTION         = 0.25    # fracción conservadora del Kelly óptimo


class OrderExecutor:
    """
    Ejecuta órdenes límite en Alpaca (paper o live según base_url).
    Aplica filtros de calidad del modelo y gestión de riesgo (Kelly fraccionado).
    """

    def __init__(self, api_key: str, secret_key: str, base_url: str = PAPER_URL):
        self.base_url = base_url
        self.api = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url=base_url,
        )

    # ------------------------------------------------------------------ #
    #  Consultas de cuenta y posición                                      #
    # ------------------------------------------------------------------ #

    def get_account(self) -> dict:
        a = self.api.get_account()
        return {
            "buying_power":    float(a.buying_power),
            "portfolio_value": float(a.portfolio_value),
            "cash":            float(a.cash),
        }

    def get_portfolio_pnl(self, date_start: str, date_end: str) -> dict:
        """Retorna P&L del rango. date_start/date_end en formato YYYY-MM-DD."""
        try:
            hist      = self.api.get_portfolio_history(
                timeframe="1D", date_start=date_start, date_end=date_end
            )
            equities  = [e for e in hist.equity if e is not None]
            if len(equities) < 2:
                return {"pnl": 0.0, "pnl_pct": 0.0}
            start_eq  = float(equities[0])
            end_eq    = float(equities[-1])
            pnl       = end_eq - start_eq
            pnl_pct   = (pnl / start_eq * 100) if start_eq > 0 else 0.0
            return {"pnl": pnl, "pnl_pct": pnl_pct}
        except Exception:
            return {"pnl": 0.0, "pnl_pct": 0.0}

    def get_position(self, symbol: str) -> dict | None:
        try:
            p = self.api.get_position(symbol.upper())
            return {
                "qty":             float(p.qty),
                "market_value":    float(p.market_value),
                "avg_entry_price": float(p.avg_entry_price),
                "side":            p.side,
            }
        except Exception:
            return None

    def get_all_positions(self) -> list[dict]:
        """Devuelve todas las posiciones abiertas en la cuenta de paper trading."""
        try:
            positions = self.api.list_positions()
            return [
                {
                    "symbol":          p.symbol,
                    "side":            p.side,
                    "qty":             float(p.qty),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price":   float(p.current_price),
                    "market_value":    float(p.market_value),
                    "unrealized_pl":   float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc),
                }
                for p in positions
            ]
        except Exception:
            return []

    def has_open_order(self, symbol: str) -> bool:
        try:
            orders = self.api.list_orders(status="open", symbols=[symbol.upper()])
            return len(orders) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Envío de órdenes                                                    #
    # ------------------------------------------------------------------ #

    def place_order(self, symbol: str, side: str, qty: float, limit_price: float) -> dict:
        order = self.api.submit_order(
            symbol=symbol.upper(),
            qty=round(qty, 2),
            side=side,
            type="limit",
            time_in_force="day",
            limit_price=round(limit_price, 2),
        )
        return {
            "id":          order.id,
            "symbol":      order.symbol,
            "side":        order.side,
            "qty":         float(order.qty),
            "limit_price": float(order.limit_price),
            "status":      order.status,
        }

    # ------------------------------------------------------------------ #
    #  Position sizing — Kelly fraccionado                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _kelly_size(
        backtest_metrics: dict,
        buying_power:     float,
        trade_amount:     float,
    ) -> tuple[float, str]:
        wr  = backtest_metrics.get("win_rate",  0.0)
        aw  = backtest_metrics.get("avg_win",   0.0)
        al  = abs(backtest_metrics.get("avg_loss", 0.0))
        nt  = backtest_metrics.get("n_trades",  0)

        if nt < 20 or al < 1e-6 or wr <= 0:
            return trade_amount, "monto fijo (backtest insuficiente)"

        b     = aw / al
        kelly = wr - (1 - wr) / b
        frac  = kelly * KELLY_FRACTION

        if frac <= 0:
            return 0.0, f"Kelly negativo ({kelly*100:.1f}%) — no operar"

        size = min(buying_power * frac, trade_amount)
        size = max(size, trade_amount * 0.10)
        return size, f"Kelly {KELLY_FRACTION*100:.0f}% ({frac*100:.1f}% cartera)"

    # ------------------------------------------------------------------ #
    #  Lógica principal de ejecución                                       #
    # ------------------------------------------------------------------ #

    def execute_signal(
        self,
        symbol:           str,
        signal:           str,
        pred_return:      float,
        quote:            dict,
        metrics:          dict,
        trade_amount:     float,
        backtest_metrics: dict | None = None,
    ) -> dict:
        """
        Analiza la señal del ensemble y ejecuta una orden si corresponde.

        pred_return: retorno esperado predicho por el ensemble (float).
        Retorna: {"action": "buy"|"sell"|"skip"|"error", "reason": str, "order": dict|None}
        """
        # ── Filtro 1: capacidad predictiva del modelo ─────────────────────
        dir_acc = metrics.get("oos_dir_acc", 0.0)
        if dir_acc < MIN_DIR_ACCURACY:
            return {
                "action": "skip",
                "reason": (
                    f"Modelo sin poder predictivo — Dir.Acc: {dir_acc*100:.1f}% "
                    f"(mínimo: {MIN_DIR_ACCURACY*100:.0f}%)"
                ),
                "order": None,
            }

        # ── Filtro 2: obtener estado de cuenta ────────────────────────────
        try:
            account = self.get_account()
        except Exception as exc:
            return {"action": "error", "reason": f"Error al obtener cuenta: {exc}", "order": None}

        # ── Filtro 3: orden duplicada ─────────────────────────────────────
        if self.has_open_order(symbol):
            return {
                "action": "skip",
                "reason": f"Ya existe una orden abierta para {symbol}",
                "order": None,
            }

        # ── COMPRA ────────────────────────────────────────────────────────
        if signal == "COMPRAR" and pred_return >= BUY_RETURN_THRESHOLD:
            ask = quote["ask_price"]
            if ask <= 0:
                return {"action": "skip", "reason": "Precio ask inválido", "order": None}

            if backtest_metrics:
                effective_amount, sizing_desc = self._kelly_size(
                    backtest_metrics, account["buying_power"], trade_amount
                )
                if effective_amount <= 0:
                    return {"action": "skip", "reason": sizing_desc, "order": None}
            else:
                effective_amount = trade_amount
                sizing_desc      = "monto fijo"

            qty = round(effective_amount / ask, 2)
            if qty < 0.01:
                return {
                    "action": "skip",
                    "reason": (
                        f"Monto insuficiente — ${effective_amount:,.0f} no alcanza "
                        f"para 0.01 acc de {symbol} (${ask:,.2f})"
                    ),
                    "order": None,
                }

            if account["buying_power"] < effective_amount:
                return {
                    "action": "skip",
                    "reason": (
                        f"Saldo insuficiente — disponible: ${account['buying_power']:,.2f} "
                        f"/ necesario: ${effective_amount:,.2f}"
                    ),
                    "order": None,
                }

            limit_price = round(quote["bid_price"] + 0.01, 2)
            try:
                order = self.place_order(symbol, "buy", qty, limit_price)
                logger.info(f"[{symbol}] COMPRA: {qty} acc @ ${limit_price:.2f} "
                            f"(pred {pred_return*100:+.2f}%)")
                return {
                    "action": "buy",
                    "reason": (
                        f"{qty} acc @ ${limit_price:.2f} límite "
                        f"(${qty * limit_price:,.2f} invertidos) · {sizing_desc} "
                        f"· retorno esperado {pred_return*100:+.2f}%"
                    ),
                    "order": order,
                }
            except Exception as exc:
                return {"action": "error", "reason": f"Error al enviar orden: {exc}", "order": None}

        # ── VENTA ─────────────────────────────────────────────────────────
        elif signal == "VENDER" and pred_return <= SELL_RETURN_THRESHOLD:
            position = self.get_position(symbol)
            if not position or position["qty"] <= 0:
                return {
                    "action": "skip",
                    "reason": f"No hay posición larga abierta en {symbol} para vender",
                    "order": None,
                }

            qty         = position["qty"]
            limit_price = round(max(quote["ask_price"] - 0.01, 0.01), 2)
            try:
                order = self.place_order(symbol, "sell", qty, limit_price)
                logger.info(f"[{symbol}] VENTA: {qty} acc @ ${limit_price:.2f} "
                            f"(pred {pred_return*100:+.2f}%)")
                return {
                    "action": "sell",
                    "reason": (
                        f"{qty} acc @ ${limit_price:.2f} límite "
                        f"· retorno esperado {pred_return*100:+.2f}%"
                    ),
                    "order": order,
                }
            except Exception as exc:
                return {"action": "error", "reason": f"Error al enviar orden: {exc}", "order": None}

        # ── Sin acción ────────────────────────────────────────────────────
        else:
            if "débil" in signal or signal == "NEUTRAL":
                reason = (
                    f"Señal {signal} — ret. predicho {pred_return*100:+.2f}% "
                    f"(umbral ±{BUY_RETURN_THRESHOLD*100:.1f}%)"
                )
            else:
                reason = f"Señal {signal} sin posición abierta para cerrar"
            return {"action": "skip", "reason": reason, "order": None}

    def close_position(self, symbol: str, quote: dict) -> dict:
        """Cierra la posición completa de symbol a precio límite (sin filtros de señal)."""
        position = self.get_position(symbol)
        if not position or position["qty"] <= 0:
            return {
                "action": "skip",
                "reason": f"No hay posición abierta en {symbol}",
                "order": None,
            }
        qty         = position["qty"]
        limit_price = round(max(quote["ask_price"] - 0.01, 0.01), 2)
        try:
            order = self.place_order(symbol, "sell", qty, limit_price)
            logger.info(f"[{symbol}] CIERRE MANUAL: {qty} acc @ ${limit_price:.2f}")
            return {
                "action":  "sell",
                "reason":  f"Cierre manual: {qty} acc @ ${limit_price:.2f} límite",
                "order":   order,
            }
        except Exception as exc:
            return {"action": "error", "reason": str(exc), "order": None}
