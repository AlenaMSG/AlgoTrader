import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QSizePolicy,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

DARK_BG    = "#0d0d14"
PANEL_BG   = "#12121c"
GRID_COLOR = "#1e1e2e"
TEXT_COLOR = "#c0c0e0"
GREEN      = "#00cc88"
RED        = "#ff4455"
BLUE       = "#4488ff"
ORANGE     = "#ffaa00"
PURPLE     = "#aa66ff"
GREY       = "#555577"


class BacktestWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Gráfico matplotlib ─────────────────────────────────────────────
        plt.rcParams.update({
            "figure.facecolor": DARK_BG,
            "axes.facecolor":   PANEL_BG,
            "axes.edgecolor":   GRID_COLOR,
            "axes.labelcolor":  TEXT_COLOR,
            "xtick.color":      TEXT_COLOR,
            "ytick.color":      TEXT_COLOR,
            "grid.color":       GRID_COLOR,
            "text.color":       TEXT_COLOR,
            "font.size":        9,
        })

        self.fig = plt.figure(figsize=(5, 3))
        gs = gridspec.GridSpec(
            2, 1,
            figure=self.fig,
            height_ratios=[3, 1],
            hspace=0.06,
        )
        self.ax_equity   = self.fig.add_subplot(gs[0])
        self.ax_drawdown = self.fig.add_subplot(gs[1], sharex=self.ax_equity)
        self.fig.subplots_adjust(left=0.07, right=0.97, top=0.93, bottom=0.09)

        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.canvas, stretch=3)

        # ── Panel de métricas ──────────────────────────────────────────────
        metrics_frame = QFrame()
        metrics_frame.setFrameShape(QFrame.Shape.StyledPanel)
        metrics_frame.setStyleSheet(
            "QFrame { background: #12121c; border-left: 1px solid #2a2a3a; }"
        )
        metrics_frame.setMinimumWidth(200)
        metrics_frame.setMaximumWidth(240)

        mf_layout = QVBoxLayout(metrics_frame)
        mf_layout.setContentsMargins(14, 14, 14, 14)
        mf_layout.setSpacing(8)

        title = QLabel("Métricas Backtest (OOS)")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet("color: #8888aa;")
        mf_layout.addWidget(title)

        self._metric_labels: dict[str, QLabel] = {}
        rows = [
            ("Retorno total",   "total_return",  "%"),
            ("CAGR",            "cagr",          "%"),
            ("Buy & Hold",      "bh_return",     "%"),
            ("Alpha vs B&H",    "alpha",         "%"),
            ("Sharpe ratio",    "sharpe",        ""),
            ("Max drawdown",    "max_drawdown",  "%"),
            ("Win rate",        "win_rate",      "%"),
            ("Profit factor",   "profit_factor", "×"),
            ("Nº operaciones",  "n_trades",      ""),
        ]
        for label_text, key, unit in rows:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet("color: #7777aa;")
            row_layout.addWidget(lbl, stretch=1)

            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            val_lbl.setStyleSheet("color: #c0c0e0;")
            row_layout.addWidget(val_lbl)

            self._metric_labels[key] = val_lbl
            mf_layout.addWidget(row_widget)

        mf_layout.addStretch()

        self._no_data_label = QLabel(
            "Ejecuta un análisis para\nver el backtest OOS aquí."
        )
        self._no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_data_label.setStyleSheet("color: #444466; font-size: 11px;")
        self._no_data_label.setWordWrap(True)

        root.addWidget(metrics_frame, stretch=0)

        # Placeholder inicial
        self._draw_placeholder()

    # ------------------------------------------------------------------ #

    def update(self, result: dict, symbol: str) -> None:
        """Actualiza el gráfico con el resultado del Backtester."""
        if result is None:
            self._draw_placeholder(f"{symbol}: sin datos de backtest")
            return

        equity    = result["equity"]
        bh_equity = result["bh_equity"]
        drawdown  = result["drawdown"]
        metrics   = result["metrics"]

        self.ax_equity.cla()
        self.ax_drawdown.cla()

        xs = np.arange(len(equity))

        # ── Equity curve ───────────────────────────────────────────────────
        self.ax_equity.plot(xs, bh_equity.values, color=GREY,
                            linewidth=1.2, label="Buy & Hold", alpha=0.7)
        self.ax_equity.plot(xs, equity.values, color=GREEN,
                            linewidth=1.6, label="Estrategia")
        self.ax_equity.fill_between(
            xs, 1, equity.values,
            where=(equity.values >= 1), alpha=0.08, color=GREEN,
        )
        self.ax_equity.fill_between(
            xs, 1, equity.values,
            where=(equity.values < 1), alpha=0.08, color=RED,
        )
        self.ax_equity.axhline(1, color=GREY, linewidth=0.6, linestyle="--", alpha=0.5)
        self.ax_equity.set_title(
            f"{symbol} — Backtest OOS (predicciones out-of-sample CV)",
            color=TEXT_COLOR, fontsize=10, pad=5,
        )
        self.ax_equity.legend(loc="upper left", fontsize=8, framealpha=0.2)
        self.ax_equity.grid(True, alpha=0.25)
        self.ax_equity.set_ylabel("Capital (base 1.0)", fontsize=8)

        # ── Drawdown ───────────────────────────────────────────────────────
        self.ax_drawdown.fill_between(xs, drawdown.values, 0, alpha=0.55, color=RED)
        self.ax_drawdown.plot(xs, drawdown.values, color=RED, linewidth=0.8)
        self.ax_drawdown.axhline(0, color=GREY, linewidth=0.6, alpha=0.5)
        self.ax_drawdown.set_ylabel("Drawdown", fontsize=8)
        self.ax_drawdown.grid(True, alpha=0.25)

        # Etiquetas del eje X con fechas
        step      = max(1, len(equity) // 8)
        tick_pos  = xs[::step]
        tick_lbls = [equity.index[i].strftime("%Y-%m") for i in tick_pos]
        self.ax_drawdown.set_xticks(tick_pos)
        self.ax_drawdown.set_xticklabels(tick_lbls, rotation=30, ha="right", fontsize=7)

        self.canvas.draw_idle()

        # ── Métricas ───────────────────────────────────────────────────────
        self._update_metrics(metrics)

    def _update_metrics(self, m: dict) -> None:
        def fmt(key, unit):
            val = m.get(key, None)
            if val is None:
                return "—"
            if unit == "%":
                color = GREEN if val >= 0 else RED
                txt   = f"{val * 100:+.1f}%"
            elif unit == "×":
                color = GREEN if val >= 1 else RED
                txt   = f"{val:.2f}×"
            else:
                color = TEXT_COLOR
                txt   = f"{val:.2f}" if isinstance(val, float) else str(val)
            self._metric_labels[key].setStyleSheet(f"color: {color};")
            return txt

        rows = [
            ("total_return",  "%"),
            ("cagr",          "%"),
            ("bh_return",     "%"),
            ("alpha",         "%"),
            ("sharpe",        ""),
            ("max_drawdown",  "%"),
            ("win_rate",      "%"),
            ("profit_factor", "×"),
            ("n_trades",      ""),
        ]
        for key, unit in rows:
            self._metric_labels[key].setText(fmt(key, unit))

        # Sharpe: color manual (no es %)
        sharpe = m.get("sharpe", 0)
        color  = GREEN if sharpe >= 1 else (ORANGE if sharpe >= 0 else RED)
        self._metric_labels["sharpe"].setText(f"{sharpe:.2f}")
        self._metric_labels["sharpe"].setStyleSheet(f"color: {color};")

        # Max drawdown ya es negativo, color siempre rojo
        dd = m.get("max_drawdown", 0)
        self._metric_labels["max_drawdown"].setText(f"{dd * 100:.1f}%")
        self._metric_labels["max_drawdown"].setStyleSheet(f"color: {RED};")

        # n_trades: texto plano
        self._metric_labels["n_trades"].setText(str(m.get("n_trades", 0)))
        self._metric_labels["n_trades"].setStyleSheet(f"color: {TEXT_COLOR};")

    def _draw_placeholder(self, msg: str = "") -> None:
        self.ax_equity.cla()
        self.ax_drawdown.cla()
        for ax in (self.ax_equity, self.ax_drawdown):
            ax.set_facecolor(PANEL_BG)
            ax.grid(False)
        self.ax_equity.text(
            0.5, 0.5,
            msg or "Sin datos de backtest aún.\nEjecuta un análisis primero.",
            ha="center", va="center", transform=self.ax_equity.transAxes,
            color=GREY, fontsize=10,
        )
        self.canvas.draw_idle()
        for lbl in self._metric_labels.values():
            lbl.setText("—")
            lbl.setStyleSheet(f"color: {TEXT_COLOR};")

    def clear(self) -> None:
        self._draw_placeholder()
