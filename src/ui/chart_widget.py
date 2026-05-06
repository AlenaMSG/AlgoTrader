import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.patches import Rectangle
from PyQt6.QtWidgets import QWidget, QVBoxLayout

DARK_BG    = "#0d0d14"
PANEL_BG   = "#12121c"
GRID_COLOR = "#1e1e2e"
TEXT_COLOR = "#c0c0e0"
GREEN      = "#00cc88"
RED        = "#ff4455"
BLUE       = "#4488ff"
ORANGE     = "#ffaa00"
PURPLE     = "#aa66ff"


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_figure()

    def _build_figure(self) -> None:
        plt.rcParams.update({
            "figure.facecolor":  DARK_BG,
            "axes.facecolor":    PANEL_BG,
            "axes.edgecolor":    GRID_COLOR,
            "axes.labelcolor":   TEXT_COLOR,
            "xtick.color":       TEXT_COLOR,
            "ytick.color":       TEXT_COLOR,
            "grid.color":        GRID_COLOR,
            "text.color":        TEXT_COLOR,
            "font.size":         9,
        })

        self.fig, (self.ax_price, self.ax_rsi, self.ax_vol) = plt.subplots(
            3, 1,
            figsize=(10, 7),
            gridspec_kw={"height_ratios": [3, 1, 1]},
            sharex=True,
        )
        self.fig.subplots_adjust(hspace=0.04, left=0.06, right=0.97, top=0.94, bottom=0.07)

        self.canvas = FigureCanvasQTAgg(self.fig)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    # ------------------------------------------------------------------ #

    def update_chart(self, df: pd.DataFrame, symbol: str) -> None:
        self.ax_price.cla()
        self.ax_rsi.cla()
        self.ax_vol.cla()

        n = len(df)
        xs = np.arange(n)

        # ── Price panel ────────────────────────────────────────────────
        for i, (_, row) in enumerate(df.iterrows()):
            color = GREEN if row["close"] >= row["open"] else RED
            # Wick
            self.ax_price.plot([i, i], [row["low"], row["high"]],
                               color=color, linewidth=0.7, alpha=0.9)
            # Body
            body_lo = min(row["open"], row["close"])
            body_hi = max(row["open"], row["close"])
            body_h  = max(body_hi - body_lo, row["close"] * 0.0002)
            self.ax_price.add_patch(Rectangle(
                (i - 0.35, body_lo), 0.7, body_h,
                facecolor=color, edgecolor=color, linewidth=0, alpha=0.85,
            ))

        if "SMA20" in df.columns:
            self.ax_price.plot(xs, df["SMA20"].values, color=BLUE,
                               linewidth=1.2, label="SMA 20", alpha=0.9)
        if "SMA50" in df.columns:
            self.ax_price.plot(xs, df["SMA50"].values, color=ORANGE,
                               linewidth=1.2, label="SMA 50", alpha=0.9)
        if "BB_upper" in df.columns:
            self.ax_price.fill_between(xs, df["BB_lower"].values, df["BB_upper"].values,
                                       alpha=0.08, color=PURPLE)
            self.ax_price.plot(xs, df["BB_upper"].values, color=PURPLE,
                               linewidth=0.7, linestyle="--", alpha=0.6)
            self.ax_price.plot(xs, df["BB_lower"].values, color=PURPLE,
                               linewidth=0.7, linestyle="--", alpha=0.6)

        self.ax_price.set_title(f"{symbol} — 1H", color=TEXT_COLOR, fontsize=11, pad=6)
        self.ax_price.legend(loc="upper left", fontsize=8, framealpha=0.2)
        self.ax_price.grid(True, alpha=0.3)
        self.ax_price.set_xlim(-1, n + 1)

        # ── RSI panel ──────────────────────────────────────────────────
        if "RSI" in df.columns:
            rsi = df["RSI"].values
            self.ax_rsi.plot(xs, rsi, color=PURPLE, linewidth=1.2)
            self.ax_rsi.axhline(70, color=RED,   linewidth=0.8, linestyle="--", alpha=0.7)
            self.ax_rsi.axhline(30, color=GREEN, linewidth=0.8, linestyle="--", alpha=0.7)
            self.ax_rsi.fill_between(xs, rsi, 70,
                                     where=(rsi >= 70), alpha=0.2, color=RED)
            self.ax_rsi.fill_between(xs, rsi, 30,
                                     where=(rsi <= 30), alpha=0.2, color=GREEN)
            self.ax_rsi.set_ylim(0, 100)
            self.ax_rsi.set_ylabel("RSI", color=TEXT_COLOR, fontsize=8)
            self.ax_rsi.grid(True, alpha=0.3)

        # ── Volume panel ───────────────────────────────────────────────
        vol_colors = [
            GREEN if df["close"].iloc[i] >= df["open"].iloc[i] else RED
            for i in range(n)
        ]
        self.ax_vol.bar(xs, df["volume"].values, color=vol_colors, alpha=0.7, width=0.8)
        if "VOL_SMA20" in df.columns:
            self.ax_vol.plot(xs, df["VOL_SMA20"].values,
                             color=ORANGE, linewidth=1, alpha=0.8)
        self.ax_vol.set_ylabel("Vol", color=TEXT_COLOR, fontsize=8)
        self.ax_vol.grid(True, alpha=0.3)

        # X-axis: show dates at the tick positions
        step = max(1, n // 10)
        tick_pos   = xs[::step]
        tick_dates = [df.index[i].strftime("%m/%d %H:%M") for i in tick_pos]
        self.ax_vol.set_xticks(tick_pos)
        self.ax_vol.set_xticklabels(tick_dates, rotation=30, ha="right", fontsize=7)

        self.canvas.draw_idle()

    def clear(self) -> None:
        for ax in (self.ax_price, self.ax_rsi, self.ax_vol):
            ax.cla()
            ax.set_facecolor(PANEL_BG)
        self.canvas.draw_idle()
