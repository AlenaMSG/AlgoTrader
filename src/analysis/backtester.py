"""
Backtester: simula P&L usando predicciones out-of-sample del CV.
No necesita reentrenar — reutiliza las predicciones ya generadas en los folds.

Estrategia: long-only, hold 1 día.
  - Cuando pred_return >= buy_threshold: comprar al cierre[t], vender al cierre[t+1]
  - buy_threshold es el retorno mínimo esperado (ej. 0.005 = 0.5%)
  - Aplica cost_pct en entrada y en salida (0.05% c/u → 0.1% round-trip)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class Backtester:

    def __init__(self, cost_pct: float = 0.0005, buy_threshold: float = 0.005):
        self.cost_pct      = cost_pct
        self.buy_threshold = buy_threshold   # retorno mínimo esperado para comprar

    def run(
        self,
        oos_preds: np.ndarray,
        oos_close: np.ndarray,
        oos_index: pd.DatetimeIndex,
    ) -> dict:
        """
        Simula la estrategia sobre predicciones OOS ya ordenadas cronológicamente.

        oos_preds : retornos predichos por el ensemble para cada barra OOS
        oos_close : precio de cierre de cada barra OOS
        oos_index : índice temporal correspondiente
        """
        daily_rets, trades = self._simulate(oos_preds, oos_close)

        equity    = pd.Series((1 + daily_rets).cumprod(), index=oos_index)
        bh_rets   = np.concatenate([[0.0], np.diff(oos_close) / oos_close[:-1]])
        bh_equity = pd.Series((1 + bh_rets).cumprod(), index=oos_index)
        drawdown  = ((equity - equity.cummax()) / equity.cummax()).clip(upper=0)

        metrics = self._compute_metrics(daily_rets, trades, equity, bh_equity)

        return {
            "equity":    equity,
            "bh_equity": bh_equity,
            "drawdown":  drawdown,
            "trades":    trades,
            "metrics":   metrics,
        }

    # ------------------------------------------------------------------ #

    def _simulate(
        self,
        preds:  np.ndarray,
        closes: np.ndarray,
    ) -> tuple[np.ndarray, list[dict]]:
        n          = len(preds)
        daily_rets = np.zeros(n)
        trades: list[dict] = []

        for i in range(n - 1):
            if preds[i] >= self.buy_threshold:
                entry = closes[i]     * (1 + self.cost_pct)
                exit_ = closes[i + 1] * (1 - self.cost_pct)
                ret   = (exit_ - entry) / entry
                daily_rets[i + 1] = ret
                trades.append({
                    "entry_price": closes[i],
                    "exit_price":  closes[i + 1],
                    "return_net":  ret,
                })

        return daily_rets, trades

    def _compute_metrics(
        self,
        daily_rets: np.ndarray,
        trades:     list[dict],
        equity:     pd.Series,
        bh_equity:  pd.Series,
    ) -> dict:
        bh_return = float(bh_equity.iloc[-1] - 1)
        n_trades  = len(trades)

        if n_trades == 0:
            return {
                "n_trades":      0,
                "win_rate":      0.0,
                "profit_factor": 0.0,
                "sharpe":        0.0,
                "max_drawdown":  0.0,
                "total_return":  0.0,
                "cagr":          0.0,
                "bh_return":     bh_return,
                "alpha":         0.0,
            }

        wins   = [t["return_net"] for t in trades if t["return_net"] > 0]
        losses = [t["return_net"] for t in trades if t["return_net"] <= 0]

        win_rate      = len(wins) / n_trades
        avg_win       = float(np.mean(wins))   if wins   else 0.0
        avg_loss      = float(np.mean(losses)) if losses else 0.0   # negativo
        gross_wins    = sum(wins)
        gross_losses  = abs(sum(losses)) + 1e-9
        profit_factor = gross_wins / gross_losses

        active_rets = daily_rets[daily_rets != 0]
        sharpe = 0.0
        if len(active_rets) > 1:
            sharpe = float(
                np.mean(active_rets) / (np.std(active_rets) + 1e-9) * np.sqrt(252)
            )

        roll_max     = equity.cummax()
        max_drawdown = float(((equity - roll_max) / roll_max).min())

        total_return = float(equity.iloc[-1] - 1)
        years        = max(len(equity) / 252, 0.01)
        cagr         = float(equity.iloc[-1] ** (1 / years) - 1)
        alpha        = total_return - bh_return

        return {
            "n_trades":      n_trades,
            "win_rate":      win_rate,
            "avg_win":       avg_win,
            "avg_loss":      avg_loss,
            "profit_factor": profit_factor,
            "sharpe":        sharpe,
            "max_drawdown":  max_drawdown,
            "total_return":  total_return,
            "cagr":          cagr,
            "bh_return":     bh_return,
            "alpha":         alpha,
        }
