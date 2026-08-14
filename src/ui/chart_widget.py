import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSizePolicy,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import pyqtSignal

DARK_BG    = "#0d0d14"
PANEL_BG   = "#12121c"
GRID_COLOR = "#1e1e2e"
TEXT_COLOR = "#c0c0e0"
GREEN      = "#00cc88"
RED        = "#ff4455"
BLUE       = "#4488ff"
ORANGE     = "#ffaa00"
PURPLE     = "#aa66ff"

_PERIODS = {"3M": 63, "6M": 126, "1A": 252, "2A": 504, "Todo": 0}


class ChartWidget(QWidget):
    bar_clicked         = pyqtSignal(dict)
    timeframe_requested = pyqtSignal(str, str)   # (symbol, "Diario" | "1H")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._df_full: pd.DataFrame | None = None
        self._symbol: str = ""
        self._display_bars: int = 252
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Selector de período ────────────────────────────────────────────
        period_row = QHBoxLayout()
        period_row.setContentsMargins(4, 2, 4, 0)

        # ── Toggle Diario / 1H ─────────────────────────────────────────────
        _combo_style = """
            QComboBox { background: #1a1a28; color: #c0c0e0; border: 1px solid #2a2a3a;
                        border-radius: 3px; padding: 1px 4px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #12121c; color: #c0c0e0;
                                          selection-background-color: #0077cc; }
        """
        tf_lbl = QLabel("Intervalo:")
        tf_lbl.setFont(QFont("Segoe UI", 8))
        tf_lbl.setStyleSheet("color: #666688;")
        period_row.addWidget(tf_lbl)

        self._tf_combo = QComboBox()
        self._tf_combo.addItems(["Diario", "1H (5d)"])
        self._tf_combo.setFixedWidth(78)
        self._tf_combo.setFixedHeight(22)
        self._tf_combo.setFont(QFont("Segoe UI", 8))
        self._tf_combo.setStyleSheet(_combo_style)
        self._tf_combo.currentTextChanged.connect(self._on_timeframe_changed)
        period_row.addWidget(self._tf_combo)

        period_row.addSpacing(12)
        period_row.addStretch()

        lbl = QLabel("Período:")
        lbl.setFont(QFont("Segoe UI", 8))
        lbl.setStyleSheet("color: #666688;")
        period_row.addWidget(lbl)

        self._period_combo = QComboBox()
        self._period_combo.addItems(list(_PERIODS.keys()))
        self._period_combo.setCurrentText("1A")
        self._period_combo.setFixedWidth(62)
        self._period_combo.setFixedHeight(22)
        self._period_combo.setFont(QFont("Segoe UI", 8))
        self._period_combo.setStyleSheet(_combo_style)
        self._period_combo.currentTextChanged.connect(self._on_period_changed)
        period_row.addWidget(self._period_combo)
        root.addLayout(period_row)

        # ── Figura matplotlib ──────────────────────────────────────────────
        self._build_figure()
        root.addWidget(self.canvas)

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
            figsize=(4, 3),
            gridspec_kw={"height_ratios": [3, 1, 1]},
            sharex=True,
        )
        self.fig.subplots_adjust(hspace=0.04, left=0.06, right=0.97, top=0.94, bottom=0.07)

        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumSize(1, 1)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.mpl_connect("button_press_event", self._on_click)

    # ------------------------------------------------------------------ #

    def _on_timeframe_changed(self, text: str) -> None:
        if self._symbol:
            tf = "1H" if text.startswith("1H") else "Diario"
            # El selector de período solo aplica a datos diarios
            self._period_combo.setEnabled(tf == "Diario")
            self.timeframe_requested.emit(self._symbol, tf)

    def _on_period_changed(self, text: str) -> None:
        self._display_bars = _PERIODS.get(text, 252)
        if self._df_full is not None:
            self._render(self._df_full, self._symbol)

    def update_chart(self, df: pd.DataFrame, symbol: str, reset_tf: bool = False) -> None:
        self._symbol  = symbol
        self._df_full = df
        if reset_tf:
            self._tf_combo.blockSignals(True)
            self._tf_combo.setCurrentIndex(0)   # "Diario"
            self._period_combo.setEnabled(True)
            self._tf_combo.blockSignals(False)
        self._render(df, symbol)

    def _render(self, df: pd.DataFrame, symbol: str) -> None:
        n_bars = self._display_bars if self._display_bars > 0 else len(df)
        self._df = df.iloc[-n_bars:].copy() if len(df) > n_bars else df.copy()
        df = self._df

        self.ax_price.cla()
        self.ax_rsi.cla()
        self.ax_vol.cla()

        n      = len(df)
        xs     = np.arange(n)
        opens  = df["open"].values
        closes = df["close"].values
        highs  = df["high"].values
        lows   = df["low"].values

        # ── Velas vectorizadas ─────────────────────────────────────────────
        up   = closes >= opens
        down = ~up

        if up.any():
            self.ax_price.vlines(xs[up],   lows[up],   highs[up],
                                 colors=GREEN, linewidth=0.7, alpha=0.9)
            self.ax_price.bar(xs[up],
                              np.maximum(closes[up] - opens[up], closes[up] * 0.0002),
                              bottom=opens[up], width=0.7, color=GREEN, linewidth=0, alpha=0.85)
        if down.any():
            self.ax_price.vlines(xs[down], lows[down], highs[down],
                                 colors=RED, linewidth=0.7, alpha=0.9)
            self.ax_price.bar(xs[down],
                              np.maximum(opens[down] - closes[down], closes[down] * 0.0002),
                              bottom=closes[down], width=0.7, color=RED, linewidth=0, alpha=0.85)

        if "sma20" in df.columns:
            self.ax_price.plot(xs, df["sma20"].values, color=BLUE,
                               linewidth=1.2, label="SMA20", alpha=0.9)
        if "sma50" in df.columns:
            self.ax_price.plot(xs, df["sma50"].values, color=ORANGE,
                               linewidth=1.2, label="SMA50", alpha=0.9)
        if "bb_upper" in df.columns:
            self.ax_price.fill_between(xs, df["bb_lower"].values, df["bb_upper"].values,
                                       alpha=0.08, color=PURPLE)
            self.ax_price.plot(xs, df["bb_upper"].values, color=PURPLE,
                               linewidth=0.7, linestyle="--", alpha=0.6)
            self.ax_price.plot(xs, df["bb_lower"].values, color=PURPLE,
                               linewidth=0.7, linestyle="--", alpha=0.6)

        period_label = self._period_combo.currentText()
        self.ax_price.set_title(
            f"{symbol} — {period_label}", color=TEXT_COLOR, fontsize=11, pad=6
        )
        self.ax_price.legend(loc="upper left", fontsize=8, framealpha=0.2)
        self.ax_price.grid(True, alpha=0.3)
        self.ax_price.set_xlim(-1, n + 1)

        # ── RSI ───────────────────────────────────────────────────────────
        if "rsi" in df.columns:
            rsi = df["rsi"].values
            self.ax_rsi.plot(xs, rsi, color=PURPLE, linewidth=1.2)
            self.ax_rsi.axhline(70, color=RED,   linewidth=0.8, linestyle="--", alpha=0.7)
            self.ax_rsi.axhline(30, color=GREEN, linewidth=0.8, linestyle="--", alpha=0.7)
            self.ax_rsi.fill_between(xs, rsi, 70, where=(rsi >= 70), alpha=0.2, color=RED)
            self.ax_rsi.fill_between(xs, rsi, 30, where=(rsi <= 30), alpha=0.2, color=GREEN)
            self.ax_rsi.set_ylim(0, 100)
            self.ax_rsi.set_ylabel("RSI", color=TEXT_COLOR, fontsize=8)
            self.ax_rsi.grid(True, alpha=0.3)

        # ── Volumen ───────────────────────────────────────────────────────
        vols = df["volume"].values
        if up.any():
            self.ax_vol.bar(xs[up],   vols[up],   color=GREEN, alpha=0.7, width=0.8)
        if down.any():
            self.ax_vol.bar(xs[down], vols[down], color=RED,   alpha=0.7, width=0.8)
        if "vol_sma20" in df.columns:
            self.ax_vol.plot(xs, df["vol_sma20"].values, color=ORANGE, linewidth=1, alpha=0.8)
        self.ax_vol.set_ylabel("Vol", color=TEXT_COLOR, fontsize=8)
        self.ax_vol.grid(True, alpha=0.3)

        step       = max(1, n // 10)
        tick_pos   = xs[::step]
        tick_dates = [df.index[i].strftime("%b %d") for i in tick_pos]
        self.ax_vol.set_xticks(tick_pos)
        self.ax_vol.set_xticklabels(tick_dates, rotation=30, ha="right", fontsize=7)

        self.canvas.draw_idle()

    # ------------------------------------------------------------------ #

    def _on_click(self, event) -> None:
        if event.inaxes is None or self._df is None or event.xdata is None:
            return
        bar_idx = int(round(event.xdata))
        if not (0 <= bar_idx < len(self._df)):
            return
        row = self._df.iloc[bar_idx]
        self.bar_clicked.emit({
            "date":    self._df.index[bar_idx],
            "row":     row,
            "symbol":  self._symbol,
            "bar_idx": bar_idx,
            "n_bars":  len(self._df),
        })

    def clear(self) -> None:
        self._df_full = None
        self._df      = None
        self._symbol  = ""
        for ax in (self.ax_price, self.ax_rsi, self.ax_vol):
            ax.cla()
            ax.set_facecolor(PANEL_BG)
        self.canvas.draw_idle()
