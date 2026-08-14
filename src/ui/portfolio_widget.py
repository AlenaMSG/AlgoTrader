"""
PortfolioWidget: pestaña de portfolio con posiciones abiertas,
equity curve de P&L realizado e historial de alertas del scanner.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

DARK_BG    = "#0d0d14"
PANEL_BG   = "#12121c"
GRID_COLOR = "#1e1e2e"
TEXT_COLOR = "#c0c0e0"
GREEN      = "#00cc88"
RED        = "#ff4455"
ORANGE     = "#ffaa00"
PURPLE     = "#aa66ff"


class PortfolioWidget(QWidget):
    """
    Muestra:
    - Resumen de cuenta Alpaca (portfolio value, buying power, cash)
    - Tabla de posiciones abiertas en tiempo real
    - Curva de P&L realizado acumulado (orders_log.csv)
    - Historial de alertas del scanner (scan_log.csv)
    """

    def __init__(self, executor=None, project_root: Path | None = None, parent=None):
        super().__init__(parent)
        self._executor    = executor
        self._root        = Path(project_root) if project_root else Path(".")
        self._build_ui()

    # ── Construcción ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # ── Header: título + cuenta + botón actualizar ─────────────────
        header = QHBoxLayout()

        title = QLabel("Portfolio  —  Alpaca Paper Trading")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #c0c0e0;")
        header.addWidget(title)
        header.addStretch()

        self._update_lbl = QLabel("Sin datos  —  pulsa Actualizar")
        self._update_lbl.setFont(QFont("Segoe UI", 8))
        self._update_lbl.setStyleSheet("color: #666688;")
        header.addWidget(self._update_lbl)

        refresh_btn = QPushButton("↻  Actualizar")
        refresh_btn.setFixedHeight(28)
        refresh_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        refresh_btn.setStyleSheet(
            "QPushButton { background: #1a2a3a; color: #88aacc; border: 1px solid #2a3a4a; "
            "border-radius: 4px; padding: 0 10px; }"
            "QPushButton:hover { background: #0077cc; color: white; }"
        )
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        # ── Resumen de cuenta ──────────────────────────────────────────
        account_frame = QFrame()
        account_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        account_row = QHBoxLayout(account_frame)
        account_row.setContentsMargins(14, 8, 14, 8)
        self._acct_labels: dict[str, QLabel] = {}
        for key, caption in (
            ("portfolio_value", "Valor cartera"),
            ("buying_power",    "Poder compra"),
            ("cash",            "Efectivo"),
        ):
            col = QVBoxLayout()
            lbl_cap = QLabel(caption)
            lbl_cap.setFont(QFont("Segoe UI", 8))
            lbl_cap.setStyleSheet("color: #666688;")
            lbl_val = QLabel("—")
            lbl_val.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
            lbl_val.setStyleSheet("color: #c0c0e0;")
            col.addWidget(lbl_cap)
            col.addWidget(lbl_val)
            account_row.addLayout(col)
            account_row.addStretch()
            self._acct_labels[key] = lbl_val
        root.addWidget(account_frame)

        # ── Splitter principal ─────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a3a; }"
            "QSplitter::handle:horizontal { width: 5px; }"
        )

        # ── Izquierda: posiciones + equity curve ───────────────────────
        left = QSplitter(Qt.Orientation.Vertical)
        left.setStyleSheet(
            "QSplitter::handle { background: #2a2a3a; }"
            "QSplitter::handle:vertical { height: 5px; }"
        )

        pos_frame = QFrame()
        pos_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        pos_layout = QVBoxLayout(pos_frame)
        pos_layout.setContentsMargins(8, 6, 8, 6)
        pos_title = QLabel("Posiciones abiertas")
        pos_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        pos_title.setStyleSheet("color: #8888aa;")
        pos_layout.addWidget(pos_title)

        self._pos_table = QTableWidget(0, 7)
        self._pos_table.setHorizontalHeaderLabels(
            ["Símbolo", "Lado", "Qty", "Precio entrada", "Precio actual", "P&L $", "P&L %"]
        )
        self._pos_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._pos_table.horizontalHeader().setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._pos_table.setFont(QFont("Consolas", 9))
        self._pos_table.setAlternatingRowColors(True)
        self._pos_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pos_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pos_table.setStyleSheet(
            "QTableWidget { background: #0d0d14; alternate-background-color: #12121c; "
            "  color: #c0c0e0; gridline-color: #2a2a3a; }"
            "QHeaderView::section { background: #1a1a28; color: #8888aa; "
            "  border: 1px solid #2a2a3a; padding: 3px; }"
            "QTableWidget::item:selected { background: #0055aa; }"
        )
        pos_layout.addWidget(self._pos_table)
        left.addWidget(pos_frame)

        # Equity curve P&L
        pnl_frame = QFrame()
        pnl_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        pnl_layout = QVBoxLayout(pnl_frame)
        pnl_layout.setContentsMargins(6, 4, 6, 4)
        pnl_title = QLabel("P&L realizado acumulado  (orders_log.csv)")
        pnl_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        pnl_title.setStyleSheet("color: #8888aa;")
        pnl_layout.addWidget(pnl_title)

        plt.rcParams.update({
            "figure.facecolor": DARK_BG,
            "axes.facecolor":   PANEL_BG,
            "axes.edgecolor":   GRID_COLOR,
            "text.color":       TEXT_COLOR,
            "xtick.color":      TEXT_COLOR,
            "ytick.color":      TEXT_COLOR,
            "grid.color":       GRID_COLOR,
        })
        self._fig_pnl, self._ax_pnl = plt.subplots(figsize=(4, 2))
        self._fig_pnl.subplots_adjust(left=0.10, right=0.97, top=0.90, bottom=0.22)
        self._canvas_pnl = FigureCanvasQTAgg(self._fig_pnl)
        self._canvas_pnl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pnl_layout.addWidget(self._canvas_pnl)
        left.addWidget(pnl_frame)
        left.setSizes([260, 200])

        splitter.addWidget(left)

        # ── Derecha: historial de alertas ──────────────────────────────
        right_frame = QFrame()
        right_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 6, 8, 6)
        scan_title = QLabel("Historial de alertas del scanner  (scan_log.csv)")
        scan_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        scan_title.setStyleSheet("color: #8888aa;")
        right_layout.addWidget(scan_title)

        self._scan_table = QTableWidget(0, 6)
        self._scan_table.setHorizontalHeaderLabels(
            ["Fecha", "Símbolo", "Señal", "Ret. %", "Dir.Acc", "Sentim."]
        )
        self._scan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._scan_table.horizontalHeader().setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._scan_table.setFont(QFont("Consolas", 9))
        self._scan_table.setAlternatingRowColors(True)
        self._scan_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._scan_table.setStyleSheet(
            "QTableWidget { background: #0d0d14; alternate-background-color: #12121c; "
            "  color: #c0c0e0; gridline-color: #2a2a3a; }"
            "QHeaderView::section { background: #1a1a28; color: #8888aa; "
            "  border: 1px solid #2a2a3a; padding: 3px; }"
            "QTableWidget::item:selected { background: #0055aa; }"
        )
        right_layout.addWidget(self._scan_table)
        splitter.addWidget(right_frame)
        splitter.setSizes([560, 360])

        root.addWidget(splitter, stretch=1)

    # ── Actualización de datos ───────────────────────────────────────────

    def refresh(self) -> None:
        self._load_account()
        self._load_positions()
        self._load_pnl_chart()
        self._load_scan_history()
        self._update_lbl.setText(
            f"Actualizado: {datetime.now().strftime('%H:%M:%S')}"
        )

    def set_executor(self, executor) -> None:
        self._executor = executor

    # ── Cuenta Alpaca ────────────────────────────────────────────────────

    def _load_account(self) -> None:
        if not self._executor:
            return
        try:
            acct = self._executor.get_account()
            self._acct_labels["portfolio_value"].setText(
                f"${acct['portfolio_value']:,.2f}"
            )
            self._acct_labels["buying_power"].setText(
                f"${acct['buying_power']:,.2f}"
            )
            self._acct_labels["cash"].setText(f"${acct['cash']:,.2f}")
        except Exception:
            pass

    # ── Posiciones abiertas ──────────────────────────────────────────────

    def _load_positions(self) -> None:
        if not self._executor:
            return
        try:
            positions = self._executor.get_all_positions()
        except Exception:
            positions = []

        self._pos_table.setRowCount(len(positions))
        for row, p in enumerate(positions):
            pl       = p["unrealized_pl"]
            pl_pct   = p["unrealized_plpc"] * 100
            pl_color = GREEN if pl >= 0 else RED

            def cell(text, color=None, bold=False):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if color:
                    item.setForeground(QColor(color))
                if bold:
                    item.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
                return item

            self._pos_table.setItem(row, 0, cell(p["symbol"], "#ffffff", bold=True))
            self._pos_table.setItem(row, 1, cell(p["side"].upper()))
            self._pos_table.setItem(row, 2, cell(f"{p['qty']:.2f}"))
            self._pos_table.setItem(row, 3, cell(f"${p['avg_entry_price']:.2f}"))
            self._pos_table.setItem(row, 4, cell(f"${p['current_price']:.2f}"))
            self._pos_table.setItem(row, 5, cell(f"${pl:+.2f}", pl_color, bold=True))
            self._pos_table.setItem(row, 6, cell(f"{pl_pct:+.2f}%", pl_color))

        if not positions:
            self._pos_table.setRowCount(1)
            item = QTableWidgetItem("Sin posiciones abiertas")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor("#666688"))
            self._pos_table.setSpan(0, 0, 1, 7)
            self._pos_table.setItem(0, 0, item)

    # ── Equity curve P&L realizado ───────────────────────────────────────

    def _load_pnl_chart(self) -> None:
        log_path = self._root / "orders_log.csv"
        self._ax_pnl.cla()
        self._ax_pnl.set_facecolor(PANEL_BG)
        self._ax_pnl.grid(True, alpha=0.3)

        if not log_path.exists():
            self._ax_pnl.text(
                0.5, 0.5, "Sin órdenes registradas aún\n(orders_log.csv no existe)",
                ha="center", va="center", transform=self._ax_pnl.transAxes,
                color="#666688", fontsize=9,
            )
            self._canvas_pnl.draw_idle()
            return

        try:
            df = pd.read_csv(log_path, parse_dates=["timestamp"])
            if df.empty:
                raise ValueError("vacío")

            df = df.sort_values("timestamp")
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
            # cash_flow: compra = negativo, venta = positivo
            df["cash_flow"] = df.apply(
                lambda r: r["amount"] if r["action"] == "sell" else -r["amount"],
                axis=1,
            )
            df["cum_pnl"] = df["cash_flow"].cumsum()

            xs    = range(len(df))
            color = GREEN if df["cum_pnl"].iloc[-1] >= 0 else RED
            self._ax_pnl.plot(
                xs, df["cum_pnl"].values,
                color=color, linewidth=1.5,
            )
            self._ax_pnl.fill_between(
                xs, 0, df["cum_pnl"].values,
                alpha=0.15, color=color,
            )
            self._ax_pnl.axhline(0, color="#444466", linewidth=0.8, linestyle="--")

            # Etiquetas del eje X: fechas de las últimas 5 órdenes
            step = max(1, len(df) // 5)
            tick_pos  = list(range(0, len(df), step))
            tick_lbls = [df["timestamp"].iloc[i].strftime("%m/%d") for i in tick_pos]
            self._ax_pnl.set_xticks(tick_pos)
            self._ax_pnl.set_xticklabels(tick_lbls, fontsize=7, rotation=30, ha="right")

            last_val = df["cum_pnl"].iloc[-1]
            self._ax_pnl.set_title(
                f"P&L neto acumulado: ${last_val:+,.2f}",
                color=color, fontsize=9, pad=4,
            )

        except Exception:
            self._ax_pnl.text(
                0.5, 0.5, "Sin órdenes suficientes para mostrar",
                ha="center", va="center", transform=self._ax_pnl.transAxes,
                color="#666688", fontsize=9,
            )

        self._canvas_pnl.draw_idle()

    # ── Historial de alertas ─────────────────────────────────────────────

    def _load_scan_history(self) -> None:
        log_path = self._root / "scan_log.csv"
        self._scan_table.setRowCount(0)

        if not log_path.exists():
            self._scan_table.setRowCount(1)
            item = QTableWidgetItem("Sin escaneos ejecutados aún (scan_log.csv no existe)")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor("#666688"))
            self._scan_table.setSpan(0, 0, 1, 6)
            self._scan_table.setItem(0, 0, item)
            return

        try:
            df = pd.read_csv(log_path, encoding="utf-8")
            if df.empty:
                raise ValueError("vacío")
            # Mostrar las 200 últimas alertas, más recientes arriba
            df = df.tail(200).iloc[::-1].reset_index(drop=True)
            self._scan_table.setRowCount(len(df))

            for row, r in df.iterrows():
                signal    = str(r.get("signal", ""))
                sig_color = GREEN if "COMPRAR" in signal else RED if "VENDER" in signal else ORANGE

                def cell(text, color=None, bold=False):
                    item = QTableWidgetItem(str(text))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if color:
                        item.setForeground(QColor(color))
                    if bold:
                        item.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
                    return item

                ts = str(r.get("timestamp", ""))[:16]
                self._scan_table.setItem(row, 0, cell(ts, "#888888"))
                self._scan_table.setItem(row, 1, cell(str(r.get("symbol", "")), "#ffffff", bold=True))
                self._scan_table.setItem(row, 2, cell(signal, sig_color, bold=True))
                self._scan_table.setItem(row, 3, cell(str(r.get("pred_return_pct", "—"))))
                self._scan_table.setItem(row, 4, cell(str(r.get("dir_acc_pct", "—"))))
                self._scan_table.setItem(row, 5, cell(str(r.get("sentiment_score", "—"))))

        except Exception:
            self._scan_table.setRowCount(1)
            item = QTableWidgetItem("Error leyendo scan_log.csv")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor(RED))
            self._scan_table.setSpan(0, 0, 1, 6)
            self._scan_table.setItem(0, 0, item)
