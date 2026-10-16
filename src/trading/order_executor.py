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
# Suelo del filtro de capacidad predictiva. Se había bajado a 0.50 (azar puro)
# para que el sistema siguiera operando: causa raíz del bucle (AUDITORIA_FASE1.md,
# DECISIONS.md). No se vuelve a bajar.
MIN_DIR_ACCURACY       = 0.52
DIR_ACC_Z              = 1.96    # además, debe superar el 50% con un 95% de confianza
BUY_RETURN_THRESHOLD   = 0.005   # retorno mínimo predicho para COMPRAR (+0.5%)
SELL_RETURN_THRESHOLD  = -0.005  # retorno máximo predicho para VENDER (-0.5%)
KELLY_FRACTION         = 0.25    # fracción conservadora del Kelly óptimo


def min_dir_accuracy(n_samples: int) -> float:
    """
    Accuracy direccional mínima para operar: la del suelo MIN_DIR_ACCURACY o la
    que hace falta para que el 50% (azar) quede fuera del IC 95%, la mayor.
    El TimeSeriesSplit(5) del entrenamiento evalúa fuera de muestra ~5/6 de las filas.
    """
    n_oos = max(int(n_samples * 5 / 6), 1)
    return max(MIN_DIR_ACCURACY, 0.5 + DIR_ACC_Z * (0.25 / n_oos) ** 0.5)


def _friendly_error(exc: Exception, symbol: str) -> str:
    """Traduce los errores más comunes de la API de Alpaca a un mensaje
    entendible para el usuario final, en vez de mostrar la excepción cruda."""
    msg = str(exc).lower()

    if "insufficient qty available" in msg:
        return (
            f"No se puede completar la venta de {symbol} ahora mismo: las acciones ya "
            "están reservadas por otra orden en curso (o el pulsador se pulsó dos veces). "
            "Espera unos segundos, comprueba en 'Mi Cartera' si la orden anterior ya se "
            "ejecutó y vuelve a intentarlo si sigue quedando posición."
        )
    if "insufficient buying power" in msg:
        return (
            f"No hay suficiente capacidad de compra para {symbol}. Reduce el importe de "
            "la operación o espera a que se liberen fondos."
        )
    if "asset" in msg and ("not tradable" in msg or "not active" in msg):
        return f"{symbol} no se puede operar en este momento (activo no disponible para trading)."
    if "market is closed" in msg or "market_hours" in msg:
        return "El mercado está cerrado ahora mismo; la orden no se puede enviar hasta la próxima sesión."
    if "position does not exist" in msg:
        return f"No tienes ninguna posición abierta en {symbol} para vender."

    return f"No se pudo completar la orden de {symbol}: {exc}"


class OrderExecutor:
    """
    Ejecuta órdenes límite en Alpaca (paper o live según base_url).
    Aplica filtros de calidad del modelo y gestión de riesgo (Kelly fraccionado).
    """

    def __init__(self, api_key: str, secret_key: str, base_url: str = PAPER_URL):
        from src.data.data_loader import _apply_request_timeout

        self.base_url = base_url
        self.api = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url=base_url,
        )
        _apply_request_timeout(self.api)

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
            qty = float(p.qty)
            qty_available = float(getattr(p, "qty_available", qty))
            return {
                "qty":             qty,
                "qty_available":   qty_available,
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
        dir_acc  = metrics.get("oos_dir_acc", 0.0)
        min_acc  = min_dir_accuracy(metrics.get("n_samples", 0))
        if dir_acc < min_acc:
            return {
                "action": "skip",
                "reason": (
                    f"Modelo sin poder predictivo — Dir.Acc: {dir_acc*100:.1f}% "
                    f"(mínimo: {min_acc*100:.1f}%)"
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
                return {"action": "error", "reason": _friendly_error(exc, symbol), "order": None}

        # ── VENTA ─────────────────────────────────────────────────────────
        elif signal == "VENDER" and pred_return <= SELL_RETURN_THRESHOLD:
            position = self.get_position(symbol)
            if not position or position["qty"] <= 0:
                return {
                    "action": "skip",
                    "reason": f"No hay posición larga abierta en {symbol} para vender",
                    "order": None,
                }

            qty_available = position.get("qty_available", position["qty"])
            if qty_available <= 0:
                return {
                    "action": "skip",
                    "reason": (
                        f"Las {position['qty']} acciones de {symbol} ya están reservadas "
                        "por otra orden abierta (o pendientes de liquidación) — no hay "
                        "cantidad disponible para vender ahora mismo."
                    ),
                    "order": None,
                }

            qty         = min(position["qty"], qty_available)
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
                return {"action": "error", "reason": _friendly_error(exc, symbol), "order": None}

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

    def manual_buy(self, symbol: str, quote: dict, amount: float) -> dict:
        """
        Compra por decisión propia del usuario, SIN los filtros del modelo
        (señal, Dir.Acc, Kelly). Mantiene las protecciones operativas: orden
        duplicada, saldo, cantidad mínima y precio límite.
        """
        if amount <= 0:
            return {"action": "skip", "reason": "Importe inválido", "order": None}
        if self.has_open_order(symbol):
            return {"action": "skip", "reason": f"Ya existe una orden abierta para {symbol}", "order": None}
        try:
            account = self.get_account()
        except Exception as exc:
            return {"action": "error", "reason": f"Error al obtener cuenta: {exc}", "order": None}
        if account["buying_power"] < amount:
            return {
                "action": "skip",
                "reason": (
                    f"Saldo insuficiente — disponible: ${account['buying_power']:,.2f} "
                    f"/ necesario: ${amount:,.2f}"
                ),
                "order": None,
            }
        try:                       # cotización actual; la del análisis puede tener horas
            q = self.api.get_latest_quote(symbol.upper())
            if float(q.ap) > 0 and float(q.bp) > 0:
                quote = {"ask_price": float(q.ap), "bid_price": float(q.bp)}
        except Exception:
            pass
        ask = quote.get("ask_price") or quote.get("bid_price") or 0.0
        if ask <= 0:
            return {"action": "error", "reason": f"Sin cotización válida para {symbol}", "order": None}
        qty = round(amount / ask, 2)
        if qty < 0.01:
            return {
                "action": "skip",
                "reason": f"Monto insuficiente — ${amount:,.0f} no alcanza para 0.01 acc de {symbol} (${ask:,.2f})",
                "order": None,
            }
        limit_price = round(quote["bid_price"] + 0.01, 2) if quote.get("bid_price") else round(ask, 2)
        try:
            order = self.place_order(symbol, "buy", qty, limit_price)
            logger.info(f"[{symbol}] COMPRA MANUAL: {qty} acc @ ${limit_price:.2f}")
            return {
                "action": "buy",
                "reason": (
                    f"Compra manual (decisión propia, sin filtros del modelo): "
                    f"{qty} acc @ ${limit_price:.2f} límite (${qty * limit_price:,.2f})"
                ),
                "order": order,
            }
        except Exception as exc:
            return {"action": "error", "reason": _friendly_error(exc, symbol), "order": None}

    def close_position(self, symbol: str, quote: dict, qty: float | None = None) -> dict:
        """Cierra symbol a precio límite (sin filtros de señal). Si `qty` es None, cierra toda
        la posición; si se indica, vende esa cantidad (limitada a lo que hay en cartera)."""
        position = self.get_position(symbol)
        if not position or position["qty"] <= 0:
            return {
                "action": "skip",
                "reason": f"No hay posición abierta en {symbol}",
                "order": None,
            }
        owned         = position["qty"]
        qty_available = position.get("qty_available", owned)
        if qty_available <= 0:
            return {
                "action": "skip",
                "reason": (
                    f"Las {owned} acciones de {symbol} ya están reservadas por otra "
                    "orden abierta (o pendientes de liquidación) — no hay cantidad "
                    "disponible para cerrar la posición ahora mismo."
                ),
                "order": None,
            }
        qty = owned if qty is None else min(qty, owned)
        qty = min(qty, qty_available)
        if qty <= 0:
            return {"action": "skip", "reason": "Cantidad inválida", "order": None}
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
            return {"action": "error", "reason": _friendly_error(exc, symbol), "order": None}
