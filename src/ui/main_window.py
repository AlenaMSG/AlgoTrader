import csv
import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QFrame, QTextEdit, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QTabWidget, QComboBox, QFileDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QAction, QColor

# Hace que todos los QLabel del módulo sean seleccionables con ratón/teclado
_QLabel = QLabel
class QLabel(_QLabel):  # type: ignore[no-redef]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

from src.config.config_manager import ConfigManager
from src.data.data_loader import DataLoader
from src.data.sp100 import SP100_SYMBOLS
from src.analysis.trading_bot import TradingBot
from src.trading.order_executor import OrderExecutor
from src.ui.chart_widget import ChartWidget
from src.ui.config_dialog import ConfigDialog
from src.ui.backtest_widget import BacktestWidget
from src.ui.portfolio_widget import PortfolioWidget

PROJECT_ROOT     = Path(__file__).resolve().parents[3]
MODEL_DIR        = PROJECT_ROOT / "models"
CACHE_DIR        = PROJECT_ROOT / "data_cache"
SIGNALS_FILE     = PROJECT_ROOT / "pending_signals.json"
PREDICTIONS_LOG  = PROJECT_ROOT / "predictions_log.csv"
ANALISIS_DIR     = Path(__file__).resolve().parents[2] / "Analisis_Predicción"

PRED_LOG_FIELDS  = [
    "scan_date", "symbol", "signal", "pred_return_pct", "da_pct",
    "actual_return_pct", "actual_date", "direction_correct",
]

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


class _SortItem(QTableWidgetItem):
    """QTableWidgetItem con sort numérico via sort_key."""
    def __init__(self, text: str, sort_key: float = 0.0):
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


def _traducir_error(exc: Exception) -> str:
    tipo = type(exc).__name__
    msg  = str(exc)
    if "not found" in msg.lower() or "no data" in msg.lower() or "no devolvio" in msg.lower():
        return "Símbolo no encontrado o sin datos. Comprueba que el ticker sea correcto."
    if "barras disponibles" in msg or "Solo" in msg:
        return msg
    if "ConnectionError" in tipo or "connect" in msg.lower():
        return "Error de conexion. Comprueba tu conexion a Internet."
    if "Unauthorized" in msg or "403" in msg or "401" in msg:
        return "Credenciales de API incorrectas o caducadas. Ve a Configuración -> Editar API Keys."
    if "RateLimitError" in tipo or "429" in msg:
        return "Demasiadas peticiones. Espera unos segundos e intentalo de nuevo."
    if "ValueError" in tipo:
        return f"Error en los datos: {msg}"
    if "KeyError" in tipo:
        return f"Campo no encontrado en los datos: {msg}"
    return f"{tipo}: {msg}"


class MultiSymbolWorker(QObject):
    symbol_done  = pyqtSignal(dict)
    symbol_error = pyqtSignal(str, str)
    progress     = pyqtSignal(str)
    all_done     = pyqtSignal()

    def __init__(self, bot, symbols, start_date, return_threshold=0.0):
        super().__init__()
        self.bot              = bot
        self.symbols          = symbols
        self.start_date       = start_date
        self.return_threshold = return_threshold

    def run(self) -> None:
        for symbol in self.symbols:
            try:
                result = self.bot.run_symbol(
                    symbol,
                    start_date=self.start_date,
                    return_threshold=self.return_threshold,
                    progress=self.progress.emit,
                )
                self.symbol_done.emit(result)
            except Exception as exc:
                self.symbol_error.emit(symbol, _traducir_error(exc))
        self.all_done.emit()


class OrderWorker(QObject):
    order_done = pyqtSignal(str, dict)

    def __init__(self, executor, symbol, signal, pred_return,
                 quote, metrics, trade_amount, backtest_metrics=None):
        super().__init__()
        self.executor         = executor
        self.symbol           = symbol
        self.signal           = signal
        self.pred_return      = pred_return
        self.quote            = quote
        self.metrics          = metrics
        self.trade_amount     = trade_amount
        self.backtest_metrics = backtest_metrics

    def run(self) -> None:
        result = self.executor.execute_signal(
            symbol=self.symbol,
            signal=self.signal,
            pred_return=self.pred_return,
            quote=self.quote,
            metrics=self.metrics,
            trade_amount=self.trade_amount,
            backtest_metrics=self.backtest_metrics,
        )
        self.order_done.emit(self.symbol, result)


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config    = config
        self.executor: OrderExecutor | None = None
        self.bot       = self._build_bot()
        self._worker_thread:    QThread | None = None
        self._results:          dict[str, dict] = {}
        self._errors:           dict[str, str]  = {}
        self._order_results:    dict[str, dict] = {}
        self._order_threads:    list[QThread]   = []
        self._backtest_results: dict[str, dict] = {}
        self._scan_mode:        bool            = False

        self.setWindowTitle("AlgoTrader")
        self.setMinimumSize(900, 580)
        self._build_menu()
        self._build_ui()
        self._refresh_inicio()
        self._set_status("Listo. Ve a Análisis para analizar una accion.")

    # ── Menu ───────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        cfg_menu = self.menuBar().addMenu("Configuración")
        edit_keys = QAction("Editar API Keys...", self)
        edit_keys.triggered.connect(self._open_config_dialog)
        cfg_menu.addAction(edit_keys)

    # ── UI (4 pestanas) ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tab_main = QTabWidget()
        self.tab_main.setStyleSheet("""
            QTabWidget::pane  { border: 1px solid #2a2a3a; }
            QTabBar::tab      { background: #1a1a28; color: #8888aa;
                                padding: 9px 26px; border: 1px solid #2a2a3a;
                                border-bottom: none; margin-right: 2px;
                                font-size: 10pt; }
            QTabBar::tab:selected { background: #0d0d14; color: #ffffff;
                                    font-weight: bold; }
            QTabBar::tab:hover    { background: #2a2a3a; color: #c0c0e0; }
        """)

        # BacktestWidget: no visible pero necesario internamente
        self.backtest_widget = BacktestWidget()

        self.tab_main.addTab(self._build_inicio_tab(),          "  Inicio")
        self.tab_main.addTab(self._build_analisis_tab(),       "  Análisis Predictivo")
        self.tab_main.addTab(self._build_evolucion_tab(),      "  Evolucion del precio")
        self.portfolio_widget = PortfolioWidget(
            executor=self.executor,
            project_root=PROJECT_ROOT,
        )
        self.tab_main.addTab(self.portfolio_widget,            "  Mi Cartera")
        self.tab_main.addTab(self._build_historial_tab(),      "  Historial")
        self.tab_main.addTab(self._build_comparacion_tab(),    "  Comparación")
        self.tab_main.currentChanged.connect(self._on_tab_changed)

        root.addWidget(self.tab_main)
        self.status_bar = QLineEdit()
        self.status_bar.setReadOnly(True)
        self.status_bar.setFixedHeight(24)
        self.status_bar.setFont(QFont("Segoe UI", 9))
        self.status_bar.setStyleSheet(
            "QLineEdit { background: #0a0a12; border: none; border-top: 1px solid #2a2a3a;"
            " color: #88aacc; padding: 0 8px; }"
        )
        root.addWidget(self.status_bar)

    # ══════════════════════════════════════════════════════════════════════
    # PESTANA 0 — INICIO
    # ══════════════════════════════════════════════════════════════════════

    def _build_inicio_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: #0d0d14;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(14)

        # Banner mercado
        self._market_banner = QLabel("...")
        self._market_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._market_banner.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._market_banner.setFixedHeight(42)
        self._market_banner.setStyleSheet("border-radius: 6px; padding: 0 16px;")
        layout.addWidget(self._market_banner)

        # Tarjetas de cuenta
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        self._inicio_acct: dict[str, QLabel] = {}
        for key, caption in (
            ("portfolio_value", "Mi dinero total"),
            ("buying_power",    "Disponible para operar"),
            ("cash",            "Efectivo en cuenta"),
        ):
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 10px; }"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 14, 20, 14)
            cap_lbl = QLabel(caption)
            cap_lbl.setFont(QFont("Segoe UI", 9))
            cap_lbl.setStyleSheet("color: #6688aa; border: none;")
            val_lbl = QLabel("--")
            val_lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
            val_lbl.setStyleSheet("color: #c0c0e0; border: none;")
            cl.addWidget(cap_lbl)
            cl.addWidget(val_lbl)
            self._inicio_acct[key] = val_lbl
            cards_row.addWidget(card)
        layout.addLayout(cards_row)

        # ── Bloque P&L Año / Mes ──────────────────────────────────────────
        pnl_frame = QFrame()
        pnl_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 10px; }"
        )
        pnl_outer = QHBoxLayout(pnl_frame)
        pnl_outer.setContentsMargins(20, 12, 20, 12)
        pnl_outer.setSpacing(16)

        # Inputs de periodo
        _date_ss = (
            "QLineEdit { background: #0d0d14; border: 1px solid #2a2a3a;"
            " color: #c0c0e0; border-radius: 4px; padding: 2px 6px; font-family: Consolas; font-size: 9pt; }"
        )
        _calc_ss = (
            "QPushButton { background: #0055aa; color: white; border-radius: 4px;"
            " padding: 2px 12px; border: 1px solid #0077cc; font-size: 9pt; }"
            "QPushButton:hover { background: #0077cc; }"
        )
        now = datetime.now()
        default_pnl_start = now.replace(day=1).strftime("%d-%m-%Y")
        default_pnl_end   = now.strftime("%d-%m-%Y")

        period_col = QVBoxLayout()
        period_col.setSpacing(4)
        period_lbl = QLabel("Periodo")
        period_lbl.setFont(QFont("Segoe UI", 8))
        period_lbl.setStyleSheet("color: #6688aa; border: none;")
        period_col.addWidget(period_lbl)

        dates_row = QHBoxLayout()
        dates_row.setSpacing(6)
        self._pnl_start_input = QLineEdit(default_pnl_start)
        self._pnl_start_input.setFixedWidth(88)
        self._pnl_start_input.setFixedHeight(26)
        self._pnl_start_input.setPlaceholderText("DD-MM-AAAA")
        self._pnl_start_input.setStyleSheet(_date_ss)
        dates_row.addWidget(self._pnl_start_input)

        dates_row.addWidget(QLabel("—"))

        self._pnl_end_input = QLineEdit(default_pnl_end)
        self._pnl_end_input.setFixedWidth(88)
        self._pnl_end_input.setFixedHeight(26)
        self._pnl_end_input.setPlaceholderText("DD-MM-AAAA")
        self._pnl_end_input.setStyleSheet(_date_ss)
        dates_row.addWidget(self._pnl_end_input)

        calc_btn = QPushButton("Calcular")
        calc_btn.setFixedHeight(26)
        calc_btn.setStyleSheet(_calc_ss)
        calc_btn.clicked.connect(self._refresh_pnl)
        dates_row.addWidget(calc_btn)

        period_col.addLayout(dates_row)
        pnl_outer.addLayout(period_col)

        # Separador vertical
        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet("color: #2a2a3a;")
        pnl_outer.addWidget(vsep)

        # Valor P&L
        self._pnl_icon_lbl = QLabel("▲")
        self._pnl_icon_lbl.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self._pnl_icon_lbl.setStyleSheet("color: #00cc88; border: none;")
        pnl_outer.addWidget(self._pnl_icon_lbl)

        pnl_val_col = QVBoxLayout()
        pnl_val_col.setSpacing(2)
        self._pnl_caption_lbl = QLabel("Ganado este mes")
        self._pnl_caption_lbl.setFont(QFont("Segoe UI", 8))
        self._pnl_caption_lbl.setStyleSheet("color: #6688aa; border: none;")
        self._pnl_value_lbl = QLabel("--")
        self._pnl_value_lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self._pnl_value_lbl.setStyleSheet("color: #c0c0e0; border: none;")
        self._pnl_pct_lbl = QLabel("")
        self._pnl_pct_lbl.setFont(QFont("Segoe UI", 9))
        self._pnl_pct_lbl.setStyleSheet("color: #888888; border: none;")
        pnl_val_col.addWidget(self._pnl_caption_lbl)
        pnl_val_col.addWidget(self._pnl_value_lbl)
        pnl_val_col.addWidget(self._pnl_pct_lbl)
        pnl_outer.addLayout(pnl_val_col)
        pnl_outer.addStretch()
        layout.addWidget(pnl_frame)

        # Aviso modo
        self._modo_label = QLabel("Modo PAPER - dinero ficticio, sin riesgo real")
        self._modo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._modo_label.setFont(QFont("Segoe UI", 9))
        self._modo_label.setStyleSheet("color: #ffaa00;")
        layout.addWidget(self._modo_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a3a;")
        layout.addWidget(sep)

        # Cabecera señales
        sig_title_row = QHBoxLayout()
        sig_title = QLabel("Señales de hoy")
        sig_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        sig_title.setStyleSheet("color: #c0c0e0;")
        sig_title_row.addWidget(sig_title)
        sig_title_row.addStretch()
        self._sig_ts_label = QLabel("")
        self._sig_ts_label.setStyleSheet("color: #666688; font-size: 8pt;")
        sig_title_row.addWidget(self._sig_ts_label)
        layout.addLayout(sig_title_row)

        # Contenedor de señales
        self._signals_wrap = QWidget()
        self._inicio_signals_container = QVBoxLayout(self._signals_wrap)
        self._inicio_signals_container.setSpacing(6)
        self._inicio_signals_container.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._signals_wrap)

        layout.addStretch()

        # Boton scan
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.scan_btn = QPushButton("  Lanzar nuevo scan del S&P100")
        self.scan_btn.setFixedHeight(44)
        self.scan_btn.setMinimumWidth(260)
        self.scan_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.scan_btn.setStyleSheet(
            "QPushButton { background: #7733cc; color: white; border-radius: 7px; }"
            "QPushButton:hover { background: #9955ff; }"
            "QPushButton:disabled { background: #333355; color: #666688; }"
        )
        self.scan_btn.clicked.connect(self._run_scan)
        btn_row.addWidget(self.scan_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    def _refresh_pnl(self) -> None:
        if not self.executor:
            return
        try:
            start_raw  = self._pnl_start_input.text().strip()
            end_raw    = self._pnl_end_input.text().strip()
            date_start = datetime.strptime(start_raw, "%d-%m-%Y").strftime("%Y-%m-%d")
            date_end   = datetime.strptime(end_raw,   "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError:
            self._pnl_value_lbl.setText("Fecha invalida")
            self._pnl_pct_lbl.setText("Usa formato DD-MM-AAAA")
            return
        self._pnl_caption_lbl.setText(f"{start_raw}  →  {end_raw}")
        try:
            data    = self.executor.get_portfolio_pnl(date_start, date_end)
            pnl     = data["pnl"]
            pnl_pct = data["pnl_pct"]
            if pnl >= 0:
                self._pnl_icon_lbl.setText("▲")
                self._pnl_icon_lbl.setStyleSheet("color: #00cc88; border: none;")
                self._pnl_value_lbl.setStyleSheet("color: #00cc88; border: none;")
            else:
                self._pnl_icon_lbl.setText("▼")
                self._pnl_icon_lbl.setStyleSheet("color: #ff4455; border: none;")
                self._pnl_value_lbl.setStyleSheet("color: #ff4455; border: none;")
            self._pnl_value_lbl.setText(f"${pnl:+,.2f}")
            self._pnl_pct_lbl.setText(f"{pnl_pct:+.2f}% vs inicio del periodo")
        except Exception:
            self._pnl_value_lbl.setText("--")
            self._pnl_pct_lbl.setText("")

    def _refresh_inicio(self) -> None:
        now_utc = datetime.now(timezone.utc)
        hhmm    = now_utc.hour * 60 + now_utc.minute
        is_open = (now_utc.weekday() < 5) and (13 * 60 + 30 <= hhmm < 20 * 60)

        if is_open:
            self._market_banner.setText("MERCADO ABIERTO  -  Cierra a las 22:00 (hora España)")
            self._market_banner.setStyleSheet(
                "border-radius: 6px; background: #0a2a1a; color: #00cc88;"
                "border: 1px solid #00cc88; padding: 0 16px;"
            )
        else:
            wd       = now_utc.weekday()
            next_txt = "lunes" if wd >= 4 else "mañana"
            self._market_banner.setText(
                f"MERCADO CERRADO  -  Proxima apertura: {next_txt} a las 15:30 (hora España)"
            )
            self._market_banner.setStyleSheet(
                "border-radius: 6px; background: #1a0a0a; color: #ff6655;"
                "border: 1px solid #ff4444; padding: 0 16px;"
            )

        if self.executor:
            try:
                acct = self.executor.get_account()
                for key, val in acct.items():
                    if key in self._inicio_acct:
                        self._inicio_acct[key].setText(f"${val:,.2f}")
            except Exception:
                pass

        mode = self.config.get_trading_mode() if hasattr(self.config, "get_trading_mode") else "paper"
        if mode == "live":
            self._modo_label.setText("LIVE - Dinero REAL")
            self._modo_label.setStyleSheet("color: #ff4455; font-weight: bold;")
        else:
            self._modo_label.setText("Modo PAPER - dinero ficticio, sin riesgo real")
            self._modo_label.setStyleSheet("color: #ffaa00;")

        self._refresh_pnl()
        self._refresh_inicio_signals()

    def _refresh_inicio_signals(self) -> None:
        while self._inicio_signals_container.count():
            item = self._inicio_signals_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not SIGNALS_FILE.exists():
            lbl = QLabel("Sin señales. Usa el boton de abajo para lanzar un scan.")
            lbl.setStyleSheet("color: #666688;")
            self._inicio_signals_container.addWidget(lbl)
            return

        try:
            data = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        ts = data.get("scan_timestamp", "")[:16]
        self._sig_ts_label.setText(f"Último scan: {ts}")

        signals = data.get("signals", [])
        strong  = [s for s in signals if s["signal"] in ("COMPRAR", "VENDER")]
        weak    = [s for s in signals if "débil" in s["signal"]]
        shown   = (strong + weak)[:10]

        if not shown:
            lbl = QLabel("Sin señales activas en el ultimo scan.")
            lbl.setStyleSheet("color: #666688;")
            self._inicio_signals_container.addWidget(lbl)
            return

        for s in shown:
            sig       = s["signal"]
            ret       = s["pred_return"] * 100
            price     = s["stale_quote"].get("ask_price", 0)
            is_buy    = "COMPRAR" in sig
            is_strong = "débil" not in sig
            da        = s["metrics"].get("oos_dir_acc", 0)
            conf      = "Alta" if da >= 0.54 else "Media" if da >= 0.51 else "Baja"
            color     = "#00cc88" if is_buy else "#ff4455" if is_strong else "#ffaa00"

            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background: #12121c; border: 1px solid #2a2a3a; "
                f"border-left: 4px solid {color}; border-radius: 6px; }}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 9, 14, 9)

            sym_lbl = QLabel(s["symbol"])
            sym_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            sym_lbl.setStyleSheet("color: #ffffff; border: none;")
            sym_lbl.setMinimumWidth(80)

            sig_lbl = QLabel(sig)
            sig_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            sig_lbl.setStyleSheet(f"color: {color}; border: none;")
            sig_lbl.setMinimumWidth(170)

            ret_lbl = QLabel(f"{ret:+.2f}%")
            ret_lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            ret_lbl.setStyleSheet(f"color: {color}; border: none;")
            ret_lbl.setMinimumWidth(70)

            price_lbl = QLabel(f"${price:.2f}")
            price_lbl.setFont(QFont("Consolas", 9))
            price_lbl.setStyleSheet("color: #8888aa; border: none;")
            price_lbl.setMinimumWidth(80)

            conf_lbl = QLabel(f"Confianza: {conf}")
            conf_lbl.setFont(QFont("Segoe UI", 9))
            conf_lbl.setStyleSheet("color: #666688; border: none;")

            rl.addWidget(sym_lbl)
            rl.addWidget(sig_lbl)
            rl.addWidget(ret_lbl)
            rl.addWidget(price_lbl)
            rl.addStretch()
            rl.addWidget(conf_lbl)
            self._inicio_signals_container.addWidget(row)

    # ══════════════════════════════════════════════════════════════════════
    # PESTANA 1 — ANALISIS
    # ══════════════════════════════════════════════════════════════════════

    def _build_analisis_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # hidden symbol_input kept for compatibility
        self.symbol_input = QLineEdit()
        self.symbol_input.hide()

        _combo_ss = (
            "QComboBox { background: #1a1a28; color: #c0c0e0; border: 1px solid #2a2a3a;"
            " border-radius: 4px; padding: 0 8px; font-weight: bold; }"
            "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: right;"
            " width: 24px; border-left: 1px solid #2a2a3a; background: #1e1e30;"
            " border-radius: 0 4px 4px 0; }"
            "QComboBox::down-arrow { image: none; width: 0; height: 0;"
            " border-left: 5px solid transparent; border-right: 5px solid transparent;"
            " border-top: 6px solid #8888aa; }"
            "QComboBox QAbstractItemView { background: #12121c; color: #c0c0e0;"
            " selection-background-color: #0055aa; min-width: 180px; }"
        )

        # ── Fila 1: simbolos + Analizar ─────────────────────────────────
        self._analisis_symbols: list[str] = []
        sym_row = QHBoxLayout()
        sym_row.setSpacing(8)

        sym_lbl = QLabel("Símbolo(s):")
        sym_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        sym_lbl.setStyleSheet("color: #8888aa;")
        sym_row.addWidget(sym_lbl)

        self._analisis_combo = QComboBox()
        self._analisis_combo.setFixedHeight(30)
        self._analisis_combo.setFixedWidth(180)
        self._analisis_combo.setStyleSheet(_combo_ss)
        self._analisis_combo.addItem("Todos (S&P100)")   # índice 0 — por defecto
        for sym in sorted(SP100_SYMBOLS):
            self._analisis_combo.addItem(sym)
        self._analisis_combo.setCurrentIndex(0)
        sym_row.addWidget(self._analisis_combo)

        add_sym_btn = QPushButton("+ Agregar")
        add_sym_btn.setFixedHeight(30)
        add_sym_btn.setFont(QFont("Segoe UI", 9))
        add_sym_btn.setToolTip("Agrega el símbolo seleccionado a la lista.\nIgnorado si está seleccionado 'Todos'.")
        add_sym_btn.setStyleSheet(
            "QPushButton { background: #0055aa; color: white; border-radius: 4px;"
            " padding: 0 12px; border: 1px solid #0077cc; }"
            "QPushButton:hover { background: #0077cc; }"
        )
        add_sym_btn.clicked.connect(self._add_analisis_symbol)
        sym_row.addWidget(add_sym_btn)

        self._analisis_chips_widget = QWidget()
        self._analisis_chips_layout = QHBoxLayout(self._analisis_chips_widget)
        self._analisis_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._analisis_chips_layout.setSpacing(6)
        self._analisis_chips_layout.addStretch()
        sym_row.addWidget(self._analisis_chips_widget, stretch=1)

        evol_btn = QPushButton("↗  Evolucion del precio")
        evol_btn.setFixedHeight(30)
        evol_btn.setFont(QFont("Segoe UI", 9))
        evol_btn.setToolTip("Ver el grafico del simbolo seleccionado")
        evol_btn.setStyleSheet(
            "QPushButton { background: #1a1a2e; color: #88aadd; border: 1px solid #2a2a4a;"
            " border-radius: 4px; padding: 0 12px; }"
            "QPushButton:hover { background: #2a2a4a; color: #aaccff; }"
        )
        evol_btn.clicked.connect(lambda: self.tab_main.setCurrentIndex(2))
        sym_row.addWidget(evol_btn)

        self.train_btn = QPushButton("  Analizar")
        self.train_btn.setFixedHeight(34)
        self.train_btn.setMinimumWidth(130)
        self.train_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.train_btn.setStyleSheet(
            "QPushButton { background: #0077cc; color: white; border-radius: 5px; }"
            "QPushButton:hover { background: #0099ff; }"
            "QPushButton:disabled { background: #333355; color: #666688; }"
        )
        self.train_btn.clicked.connect(lambda: self._run_analysis())
        sym_row.addWidget(self.train_btn)

        self._update_btn = QPushButton("↻  Actualizar resultados reales")
        self._update_btn.setFixedHeight(34)
        self._update_btn.setFont(QFont("Segoe UI", 9))
        self._update_btn.setToolTip(
            "Descarga el retorno real del mercado para todas las predicciones guardadas\n"
            "en Analisis_Predicción/ cuya fecha de predicción ya haya pasado."
        )
        self._update_btn.setStyleSheet(
            "QPushButton { background: #1a2a1a; color: #88cc88; border: 1px solid #2a4a2a;"
            " border-radius: 5px; padding: 0 12px; }"
            "QPushButton:hover { background: #00aa44; color: white; }"
            "QPushButton:disabled { background: #1a2a1a; color: #445544; }"
        )
        self._update_btn.clicked.connect(self._update_actuals_manual)
        sym_row.addWidget(self._update_btn)

        layout.addLayout(sym_row)

        # ── Fila 2: toggle Filtros ───────────────────────────────────────
        self._filtros_visible = False
        self._filtros_toggle_btn = QPushButton("▶  Filtros")
        self._filtros_toggle_btn.setFixedHeight(24)
        self._filtros_toggle_btn.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._filtros_toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #6688aa; border: none;"
            " text-align: left; padding: 0 4px; }"
            "QPushButton:hover { color: #aabbdd; }"
        )
        self._filtros_toggle_btn.clicked.connect(self._toggle_filtros)
        layout.addWidget(self._filtros_toggle_btn)

        # ── Panel de filtros (oculto por defecto) ───────────────────────
        self._filtros_frame = QFrame()
        self._filtros_frame.setVisible(False)
        self._filtros_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        filtros_layout = QVBoxLayout(self._filtros_frame)
        filtros_layout.setContentsMargins(14, 10, 14, 10)
        filtros_layout.setSpacing(8)

        # Periodo
        periodo_row = QHBoxLayout()
        periodo_row.setSpacing(8)
        periodo_lbl = QLabel("Periodo:")
        periodo_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        periodo_lbl.setStyleSheet("color: #8888aa; border: none;")
        periodo_row.addWidget(periodo_lbl)

        default_inicio = "01-01-2022"
        default_fin    = datetime.now().strftime("%d-%m-%Y")

        self.start_date_input = QLineEdit(default_inicio)
        self.start_date_input.setFixedWidth(100)
        self.start_date_input.setFixedHeight(28)
        self.start_date_input.setFont(QFont("Consolas", 9))
        self.start_date_input.setToolTip(
            "Fecha de inicio del historial para entrenar el modelo (DD-MM-AAAA).\n"
            "Mas rango = mejor entrenamiento, pero mas lento."
        )
        self.start_date_input.setStyleSheet(
            "QLineEdit { background: #0d0d14; border: 1px solid #2a2a3a;"
            " color: #c0c0e0; border-radius: 4px; padding: 2px 6px; }"
        )
        periodo_row.addWidget(self.start_date_input)

        sep_lbl = QLabel("—")
        sep_lbl.setStyleSheet("color: #444466; border: none;")
        periodo_row.addWidget(sep_lbl)

        self._end_date_input = QLineEdit(default_fin)
        self._end_date_input.setFixedWidth(100)
        self._end_date_input.setFixedHeight(28)
        self._end_date_input.setFont(QFont("Consolas", 9))
        self._end_date_input.setToolTip(
            "Fecha de fin del analisis (DD-MM-AAAA).\n"
            "Si se deja vacio, se usa la fecha de hoy."
        )
        self._end_date_input.setStyleSheet(
            "QLineEdit { background: #0d0d14; border: 1px solid #2a2a3a;"
            " color: #c0c0e0; border-radius: 4px; padding: 2px 6px; }"
        )
        periodo_row.addWidget(self._end_date_input)

        periodo_row.addSpacing(20)
        thr_lbl = QLabel("% de prediccion para Comprar/Vender:")
        thr_lbl.setFont(QFont("Segoe UI", 9))
        thr_lbl.setStyleSheet("color: #8888aa; border: none;")
        periodo_row.addWidget(thr_lbl)

        self.threshold_input = QLineEdit("0.5")
        self.threshold_input.setFixedWidth(52)
        self.threshold_input.setFixedHeight(28)
        self.threshold_input.setFont(QFont("Consolas", 9))
        self.threshold_input.setToolTip(
            "- Si % es alto: hay menos señales de compra pero son mas confiables.\n"
            "- Si % es bajo: hay muchas señales de compras flojas."
        )
        self.threshold_input.setStyleSheet(
            "QLineEdit { background: #0d0d14; border: 1px solid #2a2a3a;"
            " color: #c0c0e0; border-radius: 4px; padding: 2px 6px; }"
        )
        periodo_row.addWidget(self.threshold_input)
        pct_lbl = QLabel("%")
        pct_lbl.setFont(QFont("Segoe UI", 9))
        pct_lbl.setStyleSheet("color: #8888aa; border: none;")
        periodo_row.addWidget(pct_lbl)
        periodo_row.addStretch()
        filtros_layout.addLayout(periodo_row)

        # Separador
        hsep = QFrame()
        hsep.setFrameShape(QFrame.Shape.HLine)
        hsep.setStyleSheet("color: #2a2a3a; border: none; background: #2a2a3a;")
        hsep.setFixedHeight(1)
        filtros_layout.addWidget(hsep)

        # Checkbox ejecutar compra/venta
        self.auto_exec_check = QCheckBox("Ejecutar Compra/Venta")
        self.auto_exec_check.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.auto_exec_check.setToolTip(
            "Al activar esta opcion se realizara la Compra/Venta de operaciones\n"
            "de forma automatica cuando el analisis genere una señal."
        )
        self.auto_exec_check.setStyleSheet(
            "QCheckBox { color: #ffffff; spacing: 6px; border: none; }"
            "QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #5588aa;"
            " border-radius: 3px; background: #12121c; }"
            "QCheckBox::indicator:checked { background: #0077cc; border-color: #0099ff; }"
            "QCheckBox::indicator:hover { border-color: #0099ff; }"
        )
        self.auto_exec_check.toggled.connect(self._on_exec_check_toggled)
        filtros_layout.addWidget(self.auto_exec_check)

        # Sub-campos de ejecucion (visibles solo cuando el check esta activado)
        self._exec_fields_widget = QWidget()
        self._exec_fields_widget.setVisible(False)
        self._exec_fields_widget.setStyleSheet("background: transparent;")
        exec_row = QHBoxLayout(self._exec_fields_widget)
        exec_row.setContentsMargins(22, 0, 0, 0)
        exec_row.setSpacing(10)

        amount_lbl = QLabel("Importe a gastar por operacion: $")
        amount_lbl.setFont(QFont("Segoe UI", 9))
        amount_lbl.setStyleSheet("color: #aaaacc; border: none;")
        exec_row.addWidget(amount_lbl)

        self.trade_amount_input = QLineEdit("1000")
        self.trade_amount_input.setFixedWidth(80)
        self.trade_amount_input.setFixedHeight(28)
        self.trade_amount_input.setFont(QFont("Consolas", 9))
        self.trade_amount_input.setStyleSheet(
            "QLineEdit { background: #0d0d14; border: 1px solid #2a2a3a;"
            " color: #c0c0e0; border-radius: 4px; padding: 2px 6px; }"
        )
        exec_row.addWidget(self.trade_amount_input)

        exec_row.addStretch()

        filtros_layout.addWidget(self._exec_fields_widget)
        layout.addWidget(self._filtros_frame)

        # Tabla de resultados (compacta, max 175px)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Acción", "Señal", "Ganancia esperada", "Precio", "Confianza", "Estado"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.table.setFont(QFont("Consolas", 9))
        self.table.setMinimumHeight(50)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.setStyleSheet(
            "QTableWidget { background: #0d0d14; alternate-background-color: #12121c; "
            "  color: #c0c0e0; gridline-color: #2a2a3a; }"
            "QHeaderView::section { background: #1a1a28; color: #8888aa; "
            "  border: 1px solid #2a2a3a; padding: 4px; }"
            "QTableWidget::item:selected { background: #0055aa; color: white; }"
        )
        self.table.cellClicked.connect(self._on_table_row_clicked)

        self.detail_line = QLineEdit()
        self.detail_line.setReadOnly(True)
        self.detail_line.setPlaceholderText("Haz clic en una fila para ver el detalle...")
        self.detail_line.setFont(QFont("Consolas", 9))
        self.detail_line.setFixedHeight(26)
        self.detail_line.setStyleSheet(
            "QLineEdit { background: #0d0d14; color: #c0c0e0; border: 1px solid #2a2a3a; "
            "border-radius: 3px; padding: 0 6px; }"
        )

        _hs = (
            "QSplitter::handle { background: #2a2a3a; }"
            "QSplitter::handle:vertical { height: 5px; }"
            "QSplitter::handle:horizontal { width: 5px; }"
            "QSplitter::handle:hover { background: #0077cc; }"
        )
        _card_ss = "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        _text_ss = "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; font-size: 9pt; }"

        # ── Cards de informacion en horizontal ───────────────────────────
        info_splitter = QSplitter(Qt.Orientation.Horizontal)
        info_splitter.setStyleSheet(_hs)
        info_splitter.setMinimumHeight(210)

        # Card 1 — Señal de trading
        sf_frame = QFrame(); sf_frame.setStyleSheet(_card_ss)
        sf = QVBoxLayout(sf_frame); sf.setContentsMargins(12, 10, 12, 6); sf.setSpacing(3)
        sf.addWidget(self._section_title("Señal de trading"))
        self.signal_label = QLabel("--")
        self.signal_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sf.addWidget(self.signal_label)
        self.explain_signal_label = QLabel("")
        self.explain_signal_label.setWordWrap(True)
        self.explain_signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.explain_signal_label.setFont(QFont("Segoe UI", 8))
        self.explain_signal_label.setStyleSheet("color: #aaaacc;")
        sf.addWidget(self.explain_signal_label)
        _sep = QFrame(); _sep.setFrameShape(QFrame.Shape.HLine)
        _sep.setStyleSheet("background: #2a2a3a;"); _sep.setFixedHeight(1)
        sf.addWidget(_sep)
        self.ask_label     = QLabel("Precio: --")
        self.bid_label     = QLabel("")
        self.suggest_label = QLabel("Sugerencia: --")
        self.suggest_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        self.sentiment_label = QLabel("Noticias: --")
        self.options_label   = QLabel("Presion mercado: --")
        for lbl in (self.ask_label, self.bid_label, self.suggest_label,
                    self.sentiment_label, self.options_label):
            lbl.setFont(QFont("Consolas", 9)); lbl.setWordWrap(True); sf.addWidget(lbl)
        sf.addStretch()
        info_splitter.addWidget(sf_frame)

        # Card 2 — Detalle del modelo (labels estructurados)
        mf = QFrame(); mf.setStyleSheet(_card_ss)
        ml = QVBoxLayout(mf); ml.setContentsMargins(12, 10, 12, 8); ml.setSpacing(6)
        ml.addWidget(self._section_title("Detalle del modelo"))
        self._metrics_conf_lbl = QLabel("Confianza: --")
        self._metrics_conf_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._metrics_conf_lbl.setWordWrap(True)
        ml.addWidget(self._metrics_conf_lbl)
        self._metrics_da_lbl = QLabel("Precisión direccional: --")
        self._metrics_da_lbl.setFont(QFont("Consolas", 10))
        self._metrics_da_lbl.setStyleSheet("color: #aaaacc;")
        ml.addWidget(self._metrics_da_lbl)
        self._metrics_samples_lbl = QLabel("Muestras de entrenamiento: --")
        self._metrics_samples_lbl.setFont(QFont("Consolas", 9))
        self._metrics_samples_lbl.setStyleSheet("color: #666688;")
        ml.addWidget(self._metrics_samples_lbl)
        ml.addStretch()
        # Mantener metrics_text oculto para compatibilidad (reset_signal_panel lo limpia)
        self.metrics_text = QTextEdit(); self.metrics_text.hide()
        info_splitter.addWidget(mf)

        # Card 3 — Factores (HTML con barras de progreso visuales)
        imf = QFrame(); imf.setStyleSheet(_card_ss)
        il = QVBoxLayout(imf); il.setContentsMargins(12, 10, 12, 8); il.setSpacing(4)
        il.addWidget(self._section_title("Que factores mas influyeron"))
        self.importance_text = QTextEdit()
        self.importance_text.setReadOnly(True)
        self.importance_text.setFont(QFont("Consolas", 9))
        self.importance_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #c0c0e0; }"
        )
        il.addWidget(self.importance_text)
        info_splitter.addWidget(imf)

        # Card 4 — Orden ejecutada
        orf = QFrame()
        orf.setStyleSheet("QFrame { background: #0e1218; border: 1px solid #2a3a2a; border-radius: 8px; }")
        orl = QVBoxLayout(orf); orl.setContentsMargins(12, 10, 12, 10)
        orl.addWidget(self._section_title("Orden ejecutada", color="#6aaa6a"))
        self.order_text = QTextEdit()
        self.order_text.setReadOnly(True)
        self.order_text.setFont(QFont("Consolas", 9))
        self.order_text.setStyleSheet("QTextEdit { background: #090d0d; border: none; color: #a0c0a0; }")
        self.order_text.setPlaceholderText("Sin ordenes ejecutadas aun...")
        orl.addWidget(self.order_text)
        info_splitter.addWidget(orf)

        info_splitter.setSizes([320, 210, 220, 190])
        for i in range(info_splitter.count()):
            info_splitter.setCollapsible(i, True)

        # ── Splitter vertical: tabla + cards ────────────────────────────
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        top_layout.addWidget(self.table, stretch=1)
        self.prob_label = QLabel("Ganancia esperada: --")
        self.prob_label.setFont(QFont("Segoe UI", 10))
        self.prob_label.setWordWrap(True)
        self.prob_label.setStyleSheet(
            "color: #c0c0e0; padding: 2px 4px;"
        )
        top_layout.addWidget(self.prob_label)
        top_layout.addWidget(self.detail_line)

        main_v = QSplitter(Qt.Orientation.Vertical)
        main_v.setStyleSheet(_hs)
        main_v.addWidget(top_widget)
        main_v.addWidget(info_splitter)
        main_v.setSizes([280, 230])
        main_v.setCollapsible(0, False)
        main_v.setCollapsible(1, True)

        layout.addWidget(main_v, stretch=1)
        return w

    # ══════════════════════════════════════════════════════════════════════
    # PESTANA 2 — EVOLUCION DEL PRECIO
    # ══════════════════════════════════════════════════════════════════════

    def _build_evolucion_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # Cabecera con simbolo actual
        hdr = QHBoxLayout()
        self._evolucion_sym_lbl = QLabel(
            "Selecciona un simbolo en 'Análisis Predictivo' y haz clic en una fila"
        )
        self._evolucion_sym_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._evolucion_sym_lbl.setStyleSheet("color: #8888aa;")
        hdr.addWidget(self._evolucion_sym_lbl)
        hdr.addStretch()
        back_btn = QPushButton("← Volver a Análisis Predictivo")
        back_btn.setFixedHeight(26)
        back_btn.setFont(QFont("Segoe UI", 8))
        back_btn.setStyleSheet(
            "QPushButton { background: #1a1a2e; color: #88aadd; border: 1px solid #2a2a4a;"
            " border-radius: 4px; padding: 0 10px; }"
            "QPushButton:hover { background: #2a2a4a; color: #aaccff; }"
        )
        back_btn.clicked.connect(lambda: self.tab_main.setCurrentIndex(1))
        hdr.addWidget(back_btn)
        layout.addLayout(hdr)

        # Gráfico de precio
        self.chart = ChartWidget()
        self.chart.bar_clicked.connect(self._on_bar_clicked)
        self.chart.timeframe_requested.connect(self._on_chart_timeframe_requested)

        # Detalle de la vela (derecha)
        explain_frame = QFrame()
        explain_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        ef = QVBoxLayout(explain_frame)
        ef.setContentsMargins(10, 8, 10, 8)
        ef.setSpacing(4)
        det_title = QLabel("Detalle de la vela")
        det_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        det_title.setStyleSheet("color: #8888aa;")
        ef.addWidget(det_title)
        self.explain_text = QTextEdit()
        self.explain_text.setReadOnly(True)
        self.explain_text.setFont(QFont("Consolas", 9))
        self.explain_text.setPlaceholderText(
            "Haz clic en cualquier vela del grafico para ver el detalle de ese dia..."
        )
        self.explain_text.setStyleSheet(
            "QTextEdit { background: #090d12; border: 1px solid #1a2a1a;"
            " color: #b0d0b0; border-radius: 4px; padding: 6px; }"
        )
        ef.addWidget(self.explain_text)
        explain_frame.setMinimumWidth(240)
        explain_frame.setMaximumWidth(340)

        _hs = (
            "QSplitter::handle { background: #2a2a3a; }"
            "QSplitter::handle:horizontal { width: 6px; }"
            "QSplitter::handle:hover { background: #0077cc; }"
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(_hs)
        splitter.addWidget(self.chart)
        splitter.addWidget(explain_frame)
        splitter.setSizes([820, 280])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, True)

        layout.addWidget(splitter, stretch=1)
        return w

    def _build_analisis_right_panel(self) -> QSplitter:
        panel = QSplitter(Qt.Orientation.Vertical)
        panel.setMinimumWidth(220)

        # --- Señal ---
        signal_frame = QFrame()
        signal_frame.setFrameShape(QFrame.Shape.StyledPanel)
        signal_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        sf = QVBoxLayout(signal_frame)
        sf.setSpacing(6)
        sf.setContentsMargins(14, 12, 14, 12)

        self.signal_label = QLabel("--")
        self.signal_label.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        self.signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sf.addWidget(self.signal_label)

        self.prob_label = QLabel("Ganancia esperada: --")
        self.prob_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prob_label.setFont(QFont("Segoe UI", 11))
        sf.addWidget(self.prob_label)

        self.explain_signal_label = QLabel("")
        self.explain_signal_label.setWordWrap(True)
        self.explain_signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.explain_signal_label.setFont(QFont("Segoe UI", 9))
        self.explain_signal_label.setStyleSheet("color: #aaaacc;")
        sf.addWidget(self.explain_signal_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a3a;")
        sf.addWidget(sep)

        self.ask_label       = QLabel("Precio: --")
        self.bid_label       = QLabel("")
        self.suggest_label   = QLabel("Sugerencia: --")
        self.suggest_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        self.sentiment_label = QLabel("Noticias recientes: --")
        self.options_label   = QLabel("Presion del mercado: --")
        for lbl in (self.ask_label, self.bid_label, self.suggest_label,
                    self.sentiment_label, self.options_label):
            lbl.setFont(QFont("Consolas", 10))
            sf.addWidget(lbl)

        panel.addWidget(signal_frame)

        # --- Detalle del modelo ---
        mf = QFrame()
        mf.setFrameShape(QFrame.Shape.StyledPanel)
        mf.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        ml = QVBoxLayout(mf)
        ml.setContentsMargins(14, 10, 14, 10)
        ml.addWidget(self._section_title("Detalle del modelo"))
        self.metrics_text = QTextEdit()
        self.metrics_text.setReadOnly(True)
        self.metrics_text.setFont(QFont("Consolas", 9))
        self.metrics_text.setMinimumHeight(1)
        self.metrics_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; }"
        )
        ml.addWidget(self.metrics_text)
        panel.addWidget(mf)

        # --- Factores que influyeron ---
        imf = QFrame()
        imf.setFrameShape(QFrame.Shape.StyledPanel)
        imf.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        il = QVBoxLayout(imf)
        il.setContentsMargins(14, 10, 14, 10)
        il.addWidget(self._section_title("Que factores mas influyeron"))
        self.importance_text = QTextEdit()
        self.importance_text.setReadOnly(True)
        self.importance_text.setFont(QFont("Consolas", 9))
        self.importance_text.setMinimumHeight(1)
        self.importance_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; }"
        )
        il.addWidget(self.importance_text)
        panel.addWidget(imf)

        # --- Orden ejecutada ---
        orf = QFrame()
        orf.setFrameShape(QFrame.Shape.StyledPanel)
        orf.setStyleSheet(
            "QFrame { background: #0e1218; border: 1px solid #2a3a2a; border-radius: 8px; }"
        )
        orl = QVBoxLayout(orf)
        orl.setContentsMargins(14, 10, 14, 10)
        orl.addWidget(self._section_title("Orden ejecutada", color="#6aaa6a"))
        self.order_text = QTextEdit()
        self.order_text.setReadOnly(True)
        self.order_text.setFont(QFont("Consolas", 9))
        self.order_text.setMinimumHeight(1)
        self.order_text.setStyleSheet(
            "QTextEdit { background: #090d0d; border: none; color: #a0c0a0; }"
        )
        self.order_text.setPlaceholderText("Sin ordenes ejecutadas aun...")
        orl.addWidget(self.order_text)
        panel.addWidget(orf)

        panel.setSizes([220, 150, 150, 100])
        for i in range(panel.count()):
            panel.setCollapsible(i, True)
        return panel

    @staticmethod
    def _section_title(text: str, color: str = "#8888aa") -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    # ══════════════════════════════════════════════════════════════════════
    # PESTANA 3 — HISTORIAL
    # ══════════════════════════════════════════════════════════════════════

    def _build_historial_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Estado de filtros
        self._hist_mode             = "todo"
        self._hist_selected_years: list[str] = []
        self._hist_selected_months: list[int] = []
        self._hist_weeks_back       = 0
        self._hist_df_filtered      = None

        # ── Fila superior: modo + actualizar + exportar ──────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        self._hist_mode_btns: dict[str, QPushButton] = {}
        for label, key in [("Año", "anio"), ("Mes", "mes"), ("Semana", "semana"), ("Todo", "todo")]:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            btn.setStyleSheet(self._hbtn(key == "todo"))
            btn.clicked.connect(lambda _, k=key: self._set_hist_mode(k))
            self._hist_mode_btns[key] = btn
            top_row.addWidget(btn)
        top_row.addStretch()

        ref_btn = QPushButton("  Actualizar")
        ref_btn.setFixedHeight(30)
        ref_btn.setFont(QFont("Segoe UI", 9))
        ref_btn.setStyleSheet(
            "QPushButton { background: #1a2a3a; color: #88aacc; border: 1px solid #2a3a4a;"
            " border-radius: 4px; padding: 0 10px; }"
            "QPushButton:hover { background: #0077cc; color: white; }"
        )
        ref_btn.clicked.connect(self._refresh_historial)
        top_row.addWidget(ref_btn)

        export_btn = QPushButton("  Exportar CSV")
        export_btn.setFixedHeight(30)
        export_btn.setFont(QFont("Segoe UI", 9))
        export_btn.setStyleSheet(
            "QPushButton { background: #1a3a1a; color: #88cc88; border: 1px solid #2a5a2a;"
            " border-radius: 4px; padding: 0 12px; }"
            "QPushButton:hover { background: #0a5a0a; color: white; }"
        )
        export_btn.clicked.connect(self._export_hist_csv)
        top_row.addWidget(export_btn)
        layout.addLayout(top_row)

        # ── Área de filtros dinámicos ────────────────────────────────────
        self._hist_filter_frame = QFrame()
        self._hist_filter_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 6px; }"
        )
        self._hist_filter_inner = QVBoxLayout(self._hist_filter_frame)
        self._hist_filter_inner.setContentsMargins(10, 8, 10, 8)
        self._hist_filter_inner.setSpacing(6)
        layout.addWidget(self._hist_filter_frame)

        # ── Tabla (columnas ordenables por click en cabecera) ────────────
        self._hist_table = QTableWidget(0, 5)
        self._hist_table.setHorizontalHeaderLabels(
            ["Fecha", "Acción", "Señal", "Ganancia estimada", "Confianza"]
        )
        self._hist_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._hist_table.horizontalHeader().setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._hist_table.setSortingEnabled(True)
        self._hist_table.setFont(QFont("Consolas", 9))
        self._hist_table.setAlternatingRowColors(True)
        self._hist_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._hist_table.setStyleSheet(
            "QTableWidget { background: #0d0d14; alternate-background-color: #12121c; "
            "  color: #c0c0e0; gridline-color: #2a2a3a; }"
            "QHeaderView::section { background: #1a1a28; color: #8888aa; "
            "  border: 1px solid #2a2a3a; padding: 4px; }"
            "QHeaderView::section:hover { background: #2a2a3a; color: #c0c0e0; }"
            "QTableWidget::item:selected { background: #0055aa; }"
        )
        layout.addWidget(self._hist_table, stretch=1)

        self._rebuild_filter_area()
        return w

    @staticmethod
    def _hbtn(active: bool) -> str:
        if active:
            return ("QPushButton { background: #0077cc; color: white; border-radius: 4px;"
                    " padding: 4px 18px; border: 1px solid #0099ff; }")
        return ("QPushButton { background: #1a1a28; color: #8888aa; border-radius: 4px;"
                " padding: 4px 18px; border: 1px solid #2a2a3a; }"
                "QPushButton:hover { background: #2a2a3a; color: #c0c0e0; }")

    def _set_hist_mode(self, key: str) -> None:
        self._hist_mode = key
        self._hist_selected_years.clear()
        self._hist_selected_months.clear()
        self._hist_weeks_back = 0
        for k, btn in self._hist_mode_btns.items():
            btn.setStyleSheet(self._hbtn(k == key))
        self._rebuild_filter_area()
        self._refresh_historial()

    def _rebuild_filter_area(self) -> None:
        # Limpiar área anterior
        while self._hist_filter_inner.count():
            item = self._hist_filter_inner.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        mode = self._hist_mode
        if mode == "todo":
            self._hist_filter_frame.hide()
            self._refresh_historial()
            return

        self._hist_filter_frame.show()

        if mode == "anio":
            hint = QLabel("Selecciona uno o mas anos (sin seleccion = todos):")
            hint.setStyleSheet("color: #666688; font-size: 8pt; border: none;")
            self._hist_filter_inner.addWidget(hint)

            years = self._get_hist_years()
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)
            self._hist_year_btns: dict[str, QPushButton] = {}
            for year in years:
                active = year in self._hist_selected_years
                btn = QPushButton(str(year))
                btn.setFixedHeight(28)
                btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                btn.setStyleSheet(self._hbtn(active))
                btn.clicked.connect(lambda _, y=year: self._toggle_hist_year(y))
                self._hist_year_btns[year] = btn
                row_l.addWidget(btn)
            row_l.addStretch()
            self._hist_filter_inner.addWidget(row_w)

        elif mode == "mes":
            hint = QLabel("Agrega los meses que quieres ver (puedes elegir varios):")
            hint.setStyleSheet("color: #666688; font-size: 8pt; border: none;")
            self._hist_filter_inner.addWidget(hint)

            add_w = QWidget()
            add_l = QHBoxLayout(add_w)
            add_l.setContentsMargins(0, 0, 0, 0)
            add_l.setSpacing(6)
            self._hist_month_combo = QComboBox()
            self._hist_month_combo.setFixedHeight(28)
            self._hist_month_combo.setMinimumWidth(120)
            self._hist_month_combo.setStyleSheet(
                "QComboBox { background: #1a1a28; color: #c0c0e0; border: 1px solid #2a2a3a;"
                " border-radius: 4px; padding: 0 8px; }"
                "QComboBox::drop-down { border: none; width: 20px; }"
                "QComboBox QAbstractItemView { background: #12121c; color: #c0c0e0;"
                " selection-background-color: #0055aa; }"
            )
            for num, name in MESES_ES.items():
                if num not in self._hist_selected_months:
                    self._hist_month_combo.addItem(name, num)
            add_btn = QPushButton("+ Agregar")
            add_btn.setFixedHeight(28)
            add_btn.setStyleSheet(
                "QPushButton { background: #0055aa; color: white; border-radius: 4px;"
                " padding: 0 12px; border: 1px solid #0077cc; }"
                "QPushButton:hover { background: #0077cc; }"
            )
            add_btn.clicked.connect(self._add_hist_month)
            add_l.addWidget(self._hist_month_combo)
            add_l.addWidget(add_btn)
            add_l.addStretch()
            self._hist_filter_inner.addWidget(add_w)

            # Chips de meses seleccionados
            self._hist_chips_widget = QWidget()
            self._hist_chips_layout = QHBoxLayout(self._hist_chips_widget)
            self._hist_chips_layout.setContentsMargins(0, 2, 0, 2)
            self._hist_chips_layout.setSpacing(6)
            self._hist_filter_inner.addWidget(self._hist_chips_widget)
            self._rebuild_month_chips()

        elif mode == "semana":
            hint = QLabel("Elige la semana a visualizar:")
            hint.setStyleSheet("color: #666688; font-size: 8pt; border: none;")
            self._hist_filter_inner.addWidget(hint)

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(10)

            self._hist_week_cur_btn = QPushButton("Semana actual")
            self._hist_week_cur_btn.setFixedHeight(28)
            self._hist_week_cur_btn.setFont(QFont("Segoe UI", 9))
            self._hist_week_cur_btn.setStyleSheet(self._hbtn(self._hist_weeks_back == 0))
            self._hist_week_cur_btn.clicked.connect(lambda: self._set_hist_weeks(0))
            row_l.addWidget(self._hist_week_cur_btn)

            sep = QLabel("o")
            sep.setStyleSheet("color: #666688; border: none;")
            row_l.addWidget(sep)

            self._hist_weeks_input = QLineEdit(
                str(self._hist_weeks_back) if self._hist_weeks_back > 0 else "1"
            )
            self._hist_weeks_input.setFixedWidth(48)
            self._hist_weeks_input.setFixedHeight(28)
            self._hist_weeks_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._hist_weeks_input.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self._hist_weeks_input.setStyleSheet(
                "QLineEdit { background: #1a1a28; color: #c0c0e0; border: 1px solid #2a2a3a;"
                " border-radius: 4px; padding: 0 4px; }"
                "QLineEdit:focus { border-color: #0077cc; }"
            )
            sep2 = QLabel("semanas atras")
            sep2.setStyleSheet("color: #888888; border: none;")

            ver_btn = QPushButton("Ver")
            ver_btn.setFixedHeight(28)
            ver_btn.setStyleSheet(
                "QPushButton { background: #0055aa; color: white; border-radius: 4px;"
                " padding: 0 14px; border: 1px solid #0077cc; }"
                "QPushButton:hover { background: #0077cc; }"
            )
            ver_btn.clicked.connect(self._apply_hist_weeks_input)
            self._hist_weeks_input.returnPressed.connect(self._apply_hist_weeks_input)

            row_l.addWidget(self._hist_weeks_input)
            row_l.addWidget(sep2)
            row_l.addWidget(ver_btn)
            row_l.addStretch()
            self._hist_filter_inner.addWidget(row_w)

            self._hist_week_desc = QLabel("")
            self._hist_week_desc.setStyleSheet("color: #5577aa; font-size: 8pt; border: none;")
            self._hist_filter_inner.addWidget(self._hist_week_desc)
            self._update_week_desc()

    def _get_hist_years(self) -> list[str]:
        log_path = PROJECT_ROOT / "scan_log.csv"
        if not log_path.exists():
            return [str(datetime.now().year)]
        try:
            import pandas as pd
            df = pd.read_csv(log_path, encoding="utf-8", usecols=["timestamp"])
            years = sorted(df["timestamp"].str[:4].unique().tolist(), reverse=True)
            return years if years else [str(datetime.now().year)]
        except Exception:
            return [str(datetime.now().year)]

    def _toggle_hist_year(self, year: str) -> None:
        if year in self._hist_selected_years:
            self._hist_selected_years.remove(year)
        else:
            self._hist_selected_years.append(year)
        if hasattr(self, "_hist_year_btns") and year in self._hist_year_btns:
            self._hist_year_btns[year].setStyleSheet(
                self._hbtn(year in self._hist_selected_years)
            )
        self._refresh_historial()

    def _add_hist_month(self) -> None:
        idx = self._hist_month_combo.currentIndex()
        if idx < 0:
            return
        month_num = self._hist_month_combo.itemData(idx)
        if month_num not in self._hist_selected_months:
            self._hist_selected_months.append(month_num)
            self._hist_selected_months.sort()
        self._hist_month_combo.clear()
        for num, name in MESES_ES.items():
            if num not in self._hist_selected_months:
                self._hist_month_combo.addItem(name, num)
        self._rebuild_month_chips()
        self._refresh_historial()

    def _remove_hist_month(self, month_num: int) -> None:
        if month_num in self._hist_selected_months:
            self._hist_selected_months.remove(month_num)
        self._hist_month_combo.clear()
        for num, name in MESES_ES.items():
            if num not in self._hist_selected_months:
                self._hist_month_combo.addItem(name, num)
        self._rebuild_month_chips()
        self._refresh_historial()

    def _rebuild_month_chips(self) -> None:
        while self._hist_chips_layout.count():
            item = self._hist_chips_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for month_num in self._hist_selected_months:
            chip = QFrame()
            chip.setStyleSheet(
                "QFrame { background: #0055aa; border: 1px solid #0077cc; border-radius: 12px; }"
            )
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(10, 3, 7, 3)
            cl.setSpacing(4)
            nlbl = QLabel(MESES_ES[month_num])
            nlbl.setStyleSheet("color: white; border: none; font-size: 9pt;")
            xbtn = QPushButton("×")
            xbtn.setFixedSize(16, 16)
            xbtn.setStyleSheet(
                "QPushButton { color: #aaccee; background: transparent; border: none;"
                " font-weight: bold; font-size: 11pt; padding: 0; }"
                "QPushButton:hover { color: white; }"
            )
            xbtn.clicked.connect(lambda _, m=month_num: self._remove_hist_month(m))
            cl.addWidget(nlbl)
            cl.addWidget(xbtn)
            self._hist_chips_layout.addWidget(chip)
        self._hist_chips_layout.addStretch()

    def _set_hist_weeks(self, n: int) -> None:
        self._hist_weeks_back = n
        if hasattr(self, "_hist_week_cur_btn"):
            self._hist_week_cur_btn.setStyleSheet(self._hbtn(n == 0))
        if hasattr(self, "_hist_weeks_input"):
            self._hist_weeks_input.setText(str(n) if n > 0 else "1")
        self._update_week_desc()
        self._refresh_historial()

    def _apply_hist_weeks_input(self) -> None:
        try:
            n = max(1, int(self._hist_weeks_input.text().strip()))
        except ValueError:
            n = 1
        self._set_hist_weeks(n)

    def _update_week_desc(self) -> None:
        if not hasattr(self, "_hist_week_desc"):
            return
        n = self._hist_weeks_back
        target = datetime.now() - timedelta(weeks=n)
        iso = target.isocalendar()
        if n == 0:
            self._hist_week_desc.setText(
                f"Semana {iso[1]} de {iso[0]}  (semana en curso)"
            )
        else:
            self._hist_week_desc.setText(
                f"Semana {iso[1]} de {iso[0]}  "
                f"(hace {n} {'semana' if n == 1 else 'semanas'})"
            )

    def _refresh_historial(self) -> None:
        import pandas as pd
        log_path = PROJECT_ROOT / "scan_log.csv"
        self._hist_table.setSortingEnabled(False)
        self._hist_table.setRowCount(0)
        self._hist_df_filtered = None
        if not log_path.exists():
            self._hist_table.setSortingEnabled(True)
            return
        try:
            df = pd.read_csv(log_path, encoding="utf-8")
            if df.empty:
                self._hist_table.setSortingEnabled(True)
                return

            mode = self._hist_mode
            if mode == "anio" and self._hist_selected_years:
                df = df[df["timestamp"].str[:4].isin(self._hist_selected_years)]
            elif mode == "mes" and self._hist_selected_months:
                df = df[df["timestamp"].str[5:7].astype(int).isin(self._hist_selected_months)]
            elif mode == "semana":
                n = self._hist_weeks_back
                target_dt  = datetime.now() - timedelta(weeks=n)
                tgt_year, tgt_week, _ = target_dt.isocalendar()
                def _week_match(ts):
                    try:
                        dt = datetime.strptime(str(ts)[:10], "%Y-%m-%d")
                        y, w, _ = dt.isocalendar()
                        return y == tgt_year and w == tgt_week
                    except Exception:
                        return False
                df = df[df["timestamp"].apply(_week_match)]

            if df.empty:
                self._hist_table.setRowCount(1)
                it = QTableWidgetItem("Sin datos para el filtro seleccionado")
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setForeground(QColor("#666688"))
                self._hist_table.setSpan(0, 0, 1, 5)
                self._hist_table.setItem(0, 0, it)
                self._hist_table.setSortingEnabled(True)
                return

            df = df.iloc[::-1].reset_index(drop=True)
            self._hist_df_filtered = df.copy()
            self._hist_table.setRowCount(len(df))

            CONF_RANK = {"Alta": 3.0, "Media": 2.0, "Baja": 1.0}

            for row, r in df.iterrows():
                signal = str(r.get("signal", ""))
                color  = ("#00cc88" if "COMPRAR" in signal
                          else "#ff4455" if "VENDER" in signal else "#ffaa00")
                try:
                    da_f = float(str(r.get("dir_acc_pct", 0)).replace("%", ""))
                    conf = "Alta" if da_f >= 54 else "Media" if da_f >= 51 else "Baja"
                except Exception:
                    conf = "--"
                try:
                    ret_raw = float(str(r.get("pred_return_pct", "0")).replace("%", "").replace("+", ""))
                    ret_txt = f"{ret_raw:+.2f}%"
                except Exception:
                    ret_raw = 0.0
                    ret_txt = "--"

                ts  = str(r.get("timestamp", ""))[:16]
                sym = str(r.get("symbol", ""))

                def _t(text, sort_key=None, c=None, bold=False):
                    it = (_SortItem(str(text), sort_key) if sort_key is not None
                          else QTableWidgetItem(str(text)))
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if c:
                        it.setForeground(QColor(c))
                    if bold:
                        it.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
                    return it

                self._hist_table.setItem(row, 0, _t(ts,      sort_key=ts,    c="#888888"))
                self._hist_table.setItem(row, 1, _t(sym,     sort_key=sym,   c="#ffffff", bold=True))
                self._hist_table.setItem(row, 2, _t(signal,  sort_key=signal, c=color, bold=True))
                self._hist_table.setItem(row, 3, _t(ret_txt, sort_key=ret_raw))
                self._hist_table.setItem(row, 4, _t(conf,    sort_key=CONF_RANK.get(conf, 0.0), c=color))
        except Exception as exc:
            self._set_status(f"Error al cargar historial: {exc}", error=True)
        self._hist_table.setSortingEnabled(True)

    def _export_hist_csv(self) -> None:
        import pandas as pd
        df = self._hist_df_filtered
        if df is None:
            log_path = PROJECT_ROOT / "scan_log.csv"
            if not log_path.exists():
                self._set_status("No hay historial para exportar.", error=True)
                return
            try:
                df = pd.read_csv(log_path, encoding="utf-8")
            except Exception as exc:
                self._set_status(f"Error al leer historial: {exc}", error=True)
                return

        default_name = str(
            PROJECT_ROOT / f"historial_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        )
        path, _ = QFileDialog.getSaveFileName(
            None, "Exportar historial", default_name, "CSV (*.csv)"
        )
        if path:
            try:
                df.to_csv(path, index=False, encoding="utf-8-sig", sep=";")
                self._show_export_path(path)
            except Exception as exc:
                self._set_status(f"Error al exportar: {exc}", error=True)

    def _show_export_path(self, path: str) -> None:
        p = Path(path)
        self._set_status(f"CSV exportado: {p.name}  ·  {p.parent}")

    # ══════════════════════════════════════════════════════════════════════
    # LOGICA (sin cambios)
    # ══════════════════════════════════════════════════════════════════════

    def _build_bot(self) -> TradingBot | None:
        if self.config.has_valid_config():
            api_key, secret_key = self.config.get_credentials()
            loader = DataLoader(api_key, secret_key, cache_dir=CACHE_DIR)
            self.executor = OrderExecutor(api_key, secret_key, base_url=self.config.get_base_url())
            return TradingBot(loader, model_dir=MODEL_DIR)
        self.executor = None
        return None

    def _toggle_filtros(self) -> None:
        self._filtros_visible = not self._filtros_visible
        self._filtros_frame.setVisible(self._filtros_visible)
        self._filtros_toggle_btn.setText(
            "▼  Filtros" if self._filtros_visible else "▶  Filtros"
        )

    def _on_exec_check_toggled(self, checked: bool) -> None:
        self._exec_fields_widget.setVisible(checked)

    def _add_analisis_symbol(self) -> None:
        sym = self._analisis_combo.currentText().strip().upper()
        if not sym or sym.startswith("TODOS"):
            return   # "Todos" no se agrega como chip individual
        if sym not in self._analisis_symbols:
            self._analisis_symbols.append(sym)
        self._rebuild_analisis_chips()

    def _remove_analisis_symbol(self, sym: str) -> None:
        if sym in self._analisis_symbols:
            self._analisis_symbols.remove(sym)
        self._rebuild_analisis_chips()

    def _rebuild_analisis_chips(self) -> None:
        while self._analisis_chips_layout.count():
            item = self._analisis_chips_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for sym in self._analisis_symbols:
            chip = QFrame()
            chip.setStyleSheet(
                "QFrame { background: #0055aa; border: 1px solid #0077cc; border-radius: 12px; }"
            )
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(10, 3, 7, 3)
            cl.setSpacing(4)
            nlbl = QLabel(sym)
            nlbl.setStyleSheet("color: white; border: none; font-size: 9pt; font-weight: bold;")
            xbtn = QPushButton("×")
            xbtn.setFixedSize(16, 16)
            xbtn.setStyleSheet(
                "QPushButton { color: #aaccee; background: transparent; border: none;"
                " font-weight: bold; font-size: 11pt; padding: 0; }"
                "QPushButton:hover { color: white; }"
            )
            xbtn.clicked.connect(lambda _, s=sym: self._remove_analisis_symbol(s))
            cl.addWidget(nlbl)
            cl.addWidget(xbtn)
            self._analisis_chips_layout.addWidget(chip)
        self._analisis_chips_layout.addStretch()

    def _parse_symbols(self) -> list[str]:
        # Chips tienen prioridad; si no hay chips, mirar el combo
        if self._analisis_symbols:
            return list(self._analisis_symbols)
        txt = self._analisis_combo.currentText().strip()
        if txt.startswith("Todos"):
            return list(SP100_SYMBOLS)   # todos los simbolos del S&P100
        sym = txt.upper()
        return [sym] if sym else []

    def _parse_threshold(self) -> float:
        try:
            val = float(self.threshold_input.text().strip())
            return max(0.0, min(val / 100.0, 0.05))
        except ValueError:
            return 0.0

    def _parse_start_date(self) -> str:
        raw = self.start_date_input.text().strip()
        try:
            return datetime.strptime(raw, "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError:
            return "2022-01-01"

    def _run_scan(self) -> None:
        self.tab_main.setCurrentIndex(1)
        self._run_analysis(symbols=list(SP100_SYMBOLS), scan_mode=True)

    def _run_analysis(self, symbols: list[str] | None = None, scan_mode: bool = False) -> None:
        if not self.bot:
            self._open_config_dialog()
            return
        self._scan_mode = scan_mode
        if symbols is None:
            symbols = self._parse_symbols()
        if not symbols:
            self._set_status("Error: introduce al menos un simbolo valido.", error=True)
            return
        start_date = self._parse_start_date()
        self.train_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.chart.clear()
        self._reset_signal_panel()
        self._results.clear()
        self._errors.clear()
        self.detail_line.setText("")
        self.detail_line.setStyleSheet(
            "QLineEdit { background: #0d0d14; color: #c0c0e0; border: 1px solid #2a2a3a; "
            "border-radius: 3px; padding: 0 6px; }"
        )
        self._order_results.clear()
        self._order_threads.clear()
        self._backtest_results.clear()
        self.order_text.clear()
        self.backtest_widget.clear()
        self.table.setSortingEnabled(False)
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, False)
        self.table.setRowCount(len(symbols))
        for row, sym in enumerate(symbols):
            self._set_table_row(row, sym, estado="En proceso...")
        if scan_mode:
            self._set_status(
                f"Iniciando escaneo de {len(symbols)} simbolos S&P100 "
                "(los modelos cacheados de hoy no reentrenan)..."
            )
        self._worker_thread = QThread()
        self._worker = MultiSymbolWorker(
            self.bot, symbols, start_date,
            return_threshold=self._parse_threshold(),
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._set_status)
        self._worker.symbol_done.connect(self._on_symbol_done)
        self._worker.symbol_error.connect(self._on_symbol_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.all_done.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(lambda: self.train_btn.setEnabled(True))
        self._worker_thread.finished.connect(lambda: self.scan_btn.setEnabled(True))
        self._worker_thread.start()

    def _set_table_row(self, row: int, symbol: str, result: dict = None,
                       estado: str = "", error: str = "") -> None:
        def cell(text, color=None, bold=False):
            item = QTableWidgetItem(text)
            if color:
                item.setForeground(QColor(color))
            if bold:
                item.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return item

        self.table.setItem(row, 0, cell(symbol, "#ffffff", bold=True))

        if result:
            signal      = result["signal"]
            pred_return = result["pred_return"]
            quote       = result["quote"]
            m           = result["metrics"]
            da          = m.get("oos_dir_acc", 0)
            conf        = "Alta" if da >= 0.54 else "Media" if da >= 0.51 else "Baja"
            conf_color  = "#00cc88" if da >= 0.54 else "#ffaa00" if da >= 0.51 else "#ff6655"
            sig_color   = ("#00cc88" if "COMPRAR" in signal else
                           "#ff4455" if "VENDER"  in signal else "#ffaa00")
            ret_color   = "#00cc88" if pred_return >= 0 else "#ff4455"
            self.table.setItem(row, 1, cell(signal, sig_color, bold=True))
            self.table.setItem(row, 2, cell(f"{pred_return*100:+.2f}%", ret_color))
            self.table.setItem(row, 3, cell(f"${quote['ask_price']:.2f}"))
            self.table.setItem(row, 4, cell(conf, conf_color))
            self.table.setItem(row, 5, cell("Completado", "#00cc88"))
        elif error:
            for col in range(1, 5):
                it = cell("--", "#666688")
                it.setToolTip(error)
                self.table.setItem(row, col, it)
            err = cell(f"Error: {error[:55]}", "#ff6677")
            err.setToolTip(error)
            self.table.setItem(row, 5, err)
        else:
            for col in range(1, 5):
                self.table.setItem(row, col, cell("--", "#666688"))
            self.table.setItem(row, 5, cell(estado, "#ffaa00"))

    def _find_symbol_row(self, symbol: str) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == symbol:
                return row
        return -1

    def _on_symbol_done(self, result: dict) -> None:
        symbol = result["symbol"]
        self._results[symbol] = result
        row = self._find_symbol_row(symbol)
        if row >= 0:
            self._set_table_row(row, symbol, result=result)
        # Auto-mostrar detalle solo si es un analisis de simbolo unico
        if not self._scan_mode and len(self._results) == 1:
            self._update_detail_panel(result)
        if result.get("backtest"):
            self._backtest_results[symbol] = result["backtest"]
            self.backtest_widget.update(result["backtest"], symbol)
        # Guardar en Analisis_Predicción solo en análisis manual (no scan)
        if not self._scan_mode:
            self._save_to_tracker(result)
        if self.auto_exec_check.isChecked() and self.executor:
            self._start_order_worker(result)

    def _on_symbol_error(self, symbol: str, error_msg: str) -> None:
        self._errors[symbol] = error_msg
        row = self._find_symbol_row(symbol)
        if row >= 0:
            self._set_table_row(row, symbol, error=error_msg)
        self._set_status(f"Error en {symbol}: {error_msg}", error=True)
        self.detail_line.setText(f"[{symbol}] {error_msg}")
        self.detail_line.setStyleSheet(
            "QLineEdit { background: #0d0d14; color: #ff6677; border: 1px solid #2a2a3a; "
            "border-radius: 3px; padding: 0 6px; }"
        )

    def _on_all_done(self) -> None:
        total    = self.table.rowCount()
        exitosos = len(self._results)
        fallidos = total - exitosos
        if self._scan_mode:
            n_strong = self._filter_scan_results()
            self._export_scan_log()
            self._send_telegram_scan_alert(n_strong)
            self._set_status(
                f"Escaneo S&P100 completado - {n_strong} señales fuertes "
                f"de {exitosos} analizados ({fallidos} errores)"
            )
            self._refresh_inicio_signals()
        elif exitosos == 0:
            self._set_status("Análisis completado - todos los simbolos fallaron.", error=True)
        elif fallidos > 0:
            self._set_status(f"Análisis completado - {exitosos} OK, {fallidos} con error.")
        else:
            self._set_status(f"Análisis completado - {', '.join(self._results.keys())}")
        self.table.setSortingEnabled(True)

    def _filter_scan_results(self) -> int:
        n_strong = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                self.table.setRowHidden(row, True)
                continue
            symbol = item.text()
            result = self._results.get(symbol)
            if result:
                signal  = result["signal"]
                visible = signal != "NEUTRAL"
                self.table.setRowHidden(row, not visible)
                if visible and "débil" not in signal:
                    n_strong += 1
            else:
                self.table.setRowHidden(row, True)
        return n_strong

    def _export_scan_log(self) -> None:
        log_path  = PROJECT_ROOT / "scan_log.csv"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows      = []
        pred_rows = []
        for symbol, result in self._results.items():
            signal  = result["signal"]
            metrics = result["metrics"]
            if signal == "NEUTRAL":
                continue
            rows.append({
                "timestamp":       timestamp,
                "symbol":          symbol,
                "signal":          signal,
                "pred_return_pct": f"{result['pred_return']*100:+.2f}",
                "dir_acc_pct":     f"{metrics.get('oos_dir_acc', 0)*100:.1f}",
                "ask":             f"{result['quote']['ask_price']:.4f}",
                "bid":             f"{result['quote']['bid_price']:.4f}",
                "sentiment_score": f"{result.get('sentiment', {}).get('sentiment_score', 0.0):+.2f}",
                "pc_ratio":        f"{result.get('options', {}).get('pc_ratio', 1.0):.2f}",
            })
            pred_rows.append({
                "scan_date":        timestamp,
                "symbol":           symbol,
                "signal":           signal,
                "pred_return_pct":  f"{result['pred_return']*100:+.2f}",
                "da_pct":           f"{metrics.get('oos_dir_acc', 0)*100:.1f}",
                "actual_return_pct": "",
                "actual_date":       "",
                "direction_correct": "",
            })
        if not rows:
            return
        fieldnames   = list(rows[0].keys())
        write_header = not log_path.exists()
        try:
            with log_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerows(rows)
        except Exception:
            pass
        # También registrar en predictions_log para posterior comparación
        try:
            write_pred_hdr = not PREDICTIONS_LOG.exists()
            with PREDICTIONS_LOG.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=PRED_LOG_FIELDS)
                if write_pred_hdr:
                    writer.writeheader()
                writer.writerows(pred_rows)
        except Exception:
            pass

    def _send_telegram_scan_alert(self, n_strong: int) -> None:
        token   = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        try:
            from src.notifications.telegram_notifier import send_alert
            strong = [(sym, r) for sym, r in self._results.items()
                      if r["signal"] in ("COMPRAR", "VENDER")]
            weak   = [(sym, r) for sym, r in self._results.items()
                      if "débil" in r["signal"]]
            lines  = [f"<b>AlgoTrader - Scan S&P100</b>  {datetime.now().strftime('%d/%m %H:%M')}"]
            if strong:
                lines.append(f"\n<b>{len(strong)} señales fuertes:</b>")
                for sym, r in strong[:10]:
                    icon = "COMPRA" if "COMPRAR" in r["signal"] else "VENTA"
                    lines.append(f"- <b>{sym}</b> {icon}  {r['pred_return']*100:+.2f}%")
            if weak:
                syms = ", ".join(sym for sym, _ in weak[:6])
                lines.append(f"\n<i>{len(weak)} débiles: {syms}</i>")
            if not strong and not weak:
                lines.append("\nSin señales esta sesion.")
            send_alert(token, chat_id, "\n".join(lines))
        except Exception:
            pass

    def _on_table_row_clicked(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if not item:
            return
        symbol = item.text()
        if symbol in self._results:
            self._update_detail_panel(self._results[symbol])
            # Actualizar label de simbolo en pestaña Evolución del precio
            if hasattr(self, "_evolucion_sym_lbl"):
                self._evolucion_sym_lbl.setText(
                    f"Evolucion del precio  —  {symbol}"
                )
            self.detail_line.setText(f"[{symbol}] Análisis completado correctamente.")
            self.detail_line.setStyleSheet(
                "QLineEdit { background: #0d0d14; color: #00cc88; border: 1px solid #2a2a3a; "
                "border-radius: 3px; padding: 0 6px; }"
            )
            if symbol in self._order_results:
                self._update_order_panel(symbol, self._order_results[symbol])
            if symbol in self._backtest_results:
                self.backtest_widget.update(self._backtest_results[symbol], symbol)
        elif symbol in self._errors:
            msg = self._errors[symbol]
            self.detail_line.setText(f"[{symbol}] {msg}")
            self.detail_line.setStyleSheet(
                "QLineEdit { background: #0d0d14; color: #ff6677; border: 1px solid #2a2a3a; "
                "border-radius: 3px; padding: 0 6px; }"
            )
            self._set_status(f"Error en {symbol}: {msg}", error=True)

    def _update_detail_panel(self, result: dict) -> None:
        symbol      = result["symbol"]
        signal      = result["signal"]
        pred_return = result["pred_return"]
        metrics     = result["metrics"]
        quote       = result["quote"]
        imp         = result["importance"]
        sentiment   = result.get("sentiment", {})
        options     = result.get("options", {})

        self.chart.update_chart(result["df"], symbol, reset_tf=True)

        color = ("#00cc88" if "COMPRAR" in signal else
                 "#ff4455" if "VENDER"  in signal else "#ffaa00")
        self.signal_label.setText(signal)
        self.signal_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")

        ret_color = "#00cc88" if pred_return >= 0 else "#ff4455"
        self.prob_label.setText(
            f'Ganancia esperada: <b style="color:{ret_color}">{pred_return*100:+.2f}%</b>'
        )
        self.prob_label.setTextFormat(Qt.TextFormat.RichText)

        if "COMPRAR" in signal and "débil" not in signal:
            self.explain_signal_label.setText(
                f"El robot cree que {symbol} va a SUBIR.\nRetorno estimado positivo."
            )
        elif "COMPRAR" in signal:
            self.explain_signal_label.setText(
                f"Señal de compra débil en {symbol}.\nConfianza baja — mejor esperar."
            )
        elif "VENDER" in signal and "débil" not in signal:
            self.explain_signal_label.setText(
                f"El robot cree que {symbol} va a BAJAR.\nSi tienes acciones, considera vender."
            )
        elif "VENDER" in signal:
            self.explain_signal_label.setText(
                f"Señal de venta débil en {symbol}.\nConfianza baja — mejor esperar."
            )
        else:
            self.explain_signal_label.setText(
                f"Sin señal clara hoy para {symbol}.\nLo mas seguro es no operar."
            )

        ask = quote["ask_price"]
        bid = quote["bid_price"]
        self.ask_label.setText(f"Precio actual: ${ask:.2f}")
        self.bid_label.setText("")

        if "COMPRAR" in signal:
            self.suggest_label.setText(f"Compra limite sugerida: ${bid + 0.01:.2f}")
        elif "VENDER" in signal:
            self.suggest_label.setText(f"Venta limite sugerida: ${ask - 0.01:.2f}")
        else:
            self.suggest_label.setText("Sin accion recomendada — esperar")

        sent_score = sentiment.get("sentiment_score", 0.0)
        sent_vol   = sentiment.get("sentiment_volume", 0)
        if sent_vol > 0:
            sent_txt = ("positivas" if sent_score > 0.15 else
                        "negativas" if sent_score < -0.15 else "neutras")
            sent_color = ("#00cc88" if sent_score > 0.15 else
                          "#ff4455" if sent_score < -0.15 else "#aaaaaa")
            self.sentiment_label.setText(f"Noticias recientes: {sent_txt} ({sent_vol} articulos)")
            self.sentiment_label.setStyleSheet(f"color: {sent_color};")
        else:
            self.sentiment_label.setText("Noticias recientes: sin datos")
            self.sentiment_label.setStyleSheet("color: #666688;")

        pc = options.get("pc_ratio", 1.0)
        pc_interp = ("mas inversores apuestan a que baja" if pc > 1.5 else
                     "mas inversores apuestan a que sube" if pc < 0.7 else "presion neutral")
        pc_color = "#ff4455" if pc > 1.5 else "#00cc88" if pc < 0.7 else "#aaaaaa"
        self.options_label.setText(f"Presion del mercado: {pc_interp}")
        self.options_label.setStyleSheet(f"color: {pc_color};")

        da   = metrics.get("oos_dir_acc", 0)
        conf = "Alta" if da >= 0.54 else "Media" if da >= 0.51 else "Baja"
        conf_color = "#00cc88" if da >= 0.54 else "#ffaa00" if da >= 0.51 else "#ff6655"
        self._metrics_conf_lbl.setText(f"Confianza: {conf}")
        self._metrics_conf_lbl.setStyleSheet(f"color: {conf_color}; font-size: 14pt; font-weight: bold;")
        self._metrics_da_lbl.setText(f"Precisión direccional: {da*100:.1f}%")
        self._metrics_samples_lbl.setText(
            f"Entrenado con {metrics.get('n_samples', 0):,} dias historicos"
        )

        # Factores con barra visual HTML
        top_imp = list(imp.items())[:8]
        max_score = max((v for _, v in top_imp), default=1e-9)
        rows_html = ""
        for name, score in top_imp:
            pct     = score * 100
            bar_w   = int(score / max_score * 100)
            bar_col = "#0077cc" if bar_w > 60 else "#005599" if bar_w > 30 else "#003366"
            rows_html += (
                f'<tr>'
                f'<td style="color:#c0c0e0;padding:1px 6px 1px 0;white-space:nowrap">{name}</td>'
                f'<td style="width:90px">'
                f'<div style="background:{bar_col};width:{bar_w}%;height:10px;border-radius:3px"></div>'
                f'</td>'
                f'<td style="color:#88aacc;padding:1px 0 1px 6px;text-align:right">{pct:.1f}%</td>'
                f'</tr>'
            )
        self.importance_text.setHtml(
            f'<table style="font-family:Consolas;font-size:9pt;width:100%;border-spacing:0">'
            f'{rows_html}</table>'
        )

    def _reset_signal_panel(self) -> None:
        self.signal_label.setText("...")
        self.signal_label.setStyleSheet("color: #666688;")
        self.prob_label.setText("Ganancia esperada: --")
        self.explain_signal_label.setText("")
        self.ask_label.setText("Precio: --")
        self.bid_label.setText("")
        self.suggest_label.setText("Sugerencia: --")
        self._metrics_conf_lbl.setText("Confianza: --")
        self._metrics_conf_lbl.setStyleSheet("color: #666688; font-size: 14pt; font-weight: bold;")
        self._metrics_da_lbl.setText("Precisión direccional: --")
        self._metrics_samples_lbl.setText("Muestras de entrenamiento: --")
        self.importance_text.clear()
        self.order_text.clear()
        self.explain_text.clear()

    def _on_bar_clicked(self, data: dict) -> None:
        self.explain_text.setPlainText(self._explain_bar(data))

    @staticmethod
    def _explain_bar(data: dict) -> str:
        import math
        row    = data["row"]
        date   = data["date"]
        symbol = data["symbol"]
        date_str = date.strftime("%d %b %Y") if hasattr(date, "strftime") else str(date)[:10]
        o = row.get("open",  0)
        h = row.get("high",  0)
        l = row.get("low",   0)
        c = row.get("close", 0)
        chg   = (c - o) / o * 100 if o > 0 else 0
        arrow = "sube" if chg >= 0 else "baja"
        vela  = "Alcista (cierre > apertura)" if c >= o else "Bajista (cierre < apertura)"
        rango = (h - l) / c * 100 if c > 0 else 0

        lines = [
            f"-- {symbol}  {date_str} --",
            "",
            "PRECIO",
            f"  Apertura : ${o:>10.2f}",
            f"  Cierre   : ${c:>10.2f}   {arrow} {abs(chg):.2f}%",
            f"  Maximo   : ${h:>10.2f}",
            f"  Minimo   : ${l:>10.2f}",
            f"  Rango    :  {rango:.2f}% del precio",
            f"  Tipo     :  {vela}",
            "",
        ]

        vol     = row.get("volume", 0)
        vol_sma = row.get("vol_sma20", None)
        if vol and vol > 0:
            v_str = f"{vol/1e6:.2f}M" if vol >= 1e6 else f"{vol:,.0f}"
            if vol_sma and not math.isnan(float(vol_sma)) and vol_sma > 0:
                ratio = vol / vol_sma
                interp = ("Muy elevado - movimiento con fuerte conviccion" if ratio > 1.5 else
                          "Sobre la media - confirma la direccion"          if ratio > 1.1 else
                          "Bajo - movimiento débil, poca conviccion"        if ratio < 0.7 else
                          "Normal - sin señal de volumen adicional")
                lines += [f"VOLUMEN  {v_str}  ({ratio:.1f}x media)", f"  -> {interp}", ""]
            else:
                lines += [f"VOLUMEN  {v_str}", ""]

        rsi = row.get("rsi", None)
        if rsi is not None and not math.isnan(float(rsi)):
            rsi = float(rsi)
            interp = ("Sobrecompra extrema - alta probabilidad de correccion" if rsi >= 80 else
                      "Sobrecompra - vigilar posible giro bajista"            if rsi >= 70 else
                      "Zona alcista fuerte"                                   if rsi >= 60 else
                      "Zona neutral - sin sesgo claro"                        if rsi >= 40 else
                      "Zona bajista moderada"                                 if rsi >= 30 else
                      "Sobreventa - posible rebote alcista"                   if rsi >= 20 else
                      "Sobreventa extrema - rebote muy probable")
            lines += [f"RSI (14)   {rsi:.1f}", f"  -> {interp}", ""]

        bb_u = row.get("bb_upper", None)
        bb_l = row.get("bb_lower", None)
        if bb_u is not None and bb_l is not None:
            try:
                bb_u, bb_l = float(bb_u), float(bb_l)
                if not math.isnan(bb_u) and bb_u > bb_l > 0:
                    pct    = (c - bb_l) / (bb_u - bb_l) * 100
                    interp = ("Rompiendo banda superior - sobreextension" if pct >= 95 else
                              "Cerca de banda superior - presion alcista"  if pct >= 75 else
                              "Rompiendo banda inferior - sobreextension"  if pct <= 5  else
                              "Cerca de banda inferior - presion bajista"  if pct <= 25 else
                              "Dentro del canal - consolidacion")
                    lines += [f"BANDAS BOLLINGER  {pct:.0f}% del canal",
                              f"  Sup: ${bb_u:.2f}  |  Inf: ${bb_l:.2f}",
                              f"  -> {interp}", ""]
            except (TypeError, ValueError):
                pass

        sma20 = row.get("sma20", None)
        sma50 = row.get("sma50", None)
        sma_lines = []
        for label, val in [("Media 20 dias", sma20), ("Media 50 dias", sma50)]:
            if val is not None:
                try:
                    val  = float(val)
                    if not math.isnan(val) and val > 0:
                        diff = (c - val) / val * 100
                        sign = "+" if diff >= 0 else ""
                        pos  = "por encima" if diff >= 0 else "por debajo"
                        sma_lines.append(f"  {label}: ${val:.2f}  ({sign}{diff:.1f}% — precio {pos})")
                except (TypeError, ValueError):
                    pass
        if sma_lines:
            lines += ["MEDIAS MOVILES"] + sma_lines + [""]

        macd   = row.get("macd",        None)
        macd_s = row.get("macd_signal", None)
        macd_h = row.get("macd_hist",   None)
        if macd is not None and macd_s is not None:
            try:
                macd, macd_s = float(macd), float(macd_s)
                if not math.isnan(macd) and not math.isnan(macd_s):
                    interp = ("MACD sobre señal -> momentum alcista" if macd > macd_s
                              else "MACD bajo señal -> momentum bajista")
                    h_str  = f"{float(macd_h):+.4f}" if macd_h is not None else "--"
                    lines += [f"MACD  {macd:+.4f} | Señal: {macd_s:+.4f} | Hist: {h_str}",
                              f"  -> {interp}", ""]
            except (TypeError, ValueError):
                pass

        lines.append(f"Barra {data['bar_idx'] + 1} de {data['n_bars']} mostradas")
        return "\n".join(lines)

    def _save_to_tracker(self, result: dict) -> None:
        from src.analysis import prediction_tracker
        try:
            ANALISIS_DIR.mkdir(parents=True, exist_ok=True)
            train_desde = self.start_date_input.text().strip()
            train_hasta = self._end_date_input.text().strip()
            prediction_tracker.save_real_data(ANALISIS_DIR, result["symbol"], result["df"])
            saved = prediction_tracker.save_prediction(
                ANALISIS_DIR, result["symbol"], result, train_desde, train_hasta,
            )
            if saved:
                self._set_status(
                    f"[{result['symbol']}] Guardado en Analisis_Predicción/ — "
                    f"señal {result['signal']} para {result['symbol']}"
                )
        except Exception as exc:
            self._set_status(
                f"[{result['symbol']}] Error al guardar en Analisis_Predicción: {exc}",
                error=True,
            )

    def _update_actuals_manual(self) -> None:
        from src.analysis import prediction_tracker
        self._set_status("Buscando retornos reales pendientes en Analisis_Predicción/...")
        self._update_btn.setEnabled(False)

        def _bg():
            n = prediction_tracker.update_actuals(ANALISIS_DIR)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._on_actuals_done(n))

        threading.Thread(target=_bg, daemon=True).start()

    def _on_actuals_done(self, n: int) -> None:
        self._update_btn.setEnabled(True)
        if n > 0:
            self._set_status(
                f"Actualización completada — {n} predicción{'es' if n > 1 else ''} completada{'s' if n > 1 else ''} con datos reales."
            )
        else:
            self._set_status("Sin predicciones pendientes de completar en Analisis_Predicción/.")

    def _start_order_worker(self, result: dict) -> None:
        try:
            trade_amount = float(self.trade_amount_input.text())
        except ValueError:
            trade_amount = 1000.0
        bt_metrics = None
        if result.get("backtest"):
            bt_metrics = result["backtest"].get("metrics")
        thread = QThread()
        worker = OrderWorker(
            executor=self.executor,
            symbol=result["symbol"],
            signal=result["signal"],
            pred_return=result["pred_return"],
            quote=result["quote"],
            metrics=result["metrics"],
            trade_amount=trade_amount,
            backtest_metrics=bt_metrics,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.order_done.connect(self._on_order_done)
        worker.order_done.connect(lambda: thread.quit())
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread: self._order_threads.remove(t) if t in self._order_threads else None
        )
        thread.start()
        self._order_threads.append(thread)

    def _on_order_done(self, symbol: str, exec_result: dict) -> None:
        self._order_results[symbol] = exec_result
        self._update_order_panel(symbol, exec_result)
        action = exec_result["action"]
        reason = exec_result["reason"]
        if action in ("buy", "sell"):
            self._set_status(
                f"[{symbol}] {'COMPRA' if action == 'buy' else 'VENTA'} ejecutada - {reason}"
            )
            self._log_order_csv(symbol, exec_result)
        elif action == "error":
            self._set_status(f"[{symbol}] Error en orden - {reason}", error=True)
        else:
            self._set_status(f"[{symbol}] Orden omitida - {reason}")

    def _log_order_csv(self, symbol: str, exec_result: dict) -> None:
        log_path    = PROJECT_ROOT / "orders_log.csv"
        order       = exec_result.get("order") or {}
        reason      = exec_result.get("reason", "")
        analysis    = self._results.get(symbol, {})
        metrics     = analysis.get("metrics", {})
        qty         = order.get("qty", "")
        limit_price = order.get("limit_price", "")
        amount      = round(qty * limit_price, 2) if qty and limit_price else ""
        row = {
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":      symbol,
            "action":      exec_result.get("action", ""),
            "qty":         qty,
            "limit_price": limit_price,
            "amount":      amount,
            "order_id":    order.get("id", ""),
            "signal":      analysis.get("signal", ""),
            "pred_return": f"{analysis.get('pred_return', 0.0)*100:+.3f}%" if "pred_return" in analysis else "",
            "dir_acc":     f"{metrics.get('oos_dir_acc', 0.0)*100:.1f}%" if metrics.get("oos_dir_acc") is not None else "",
            "kelly_used":  "Kelly" in reason,
        }
        fieldnames   = list(row.keys())
        write_header = not log_path.exists()
        try:
            with log_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            pass

    def _update_order_panel(self, symbol: str, exec_result: dict) -> None:
        action = exec_result["action"]
        reason = exec_result["reason"]
        order  = exec_result.get("order")
        if action == "buy":
            hc, header = "#00cc88", f"[{symbol}]  COMPRA enviada"
        elif action == "sell":
            hc, header = "#ff6655", f"[{symbol}]  VENTA enviada"
        elif action == "error":
            hc, header = "#ff4455", f"[{symbol}]  ERROR"
        else:
            hc, header = "#ffaa00", f"[{symbol}]  OMITIDA"
        order_line = ""
        if order:
            order_line = f"\nOrden ID : {order['id'][:12]}...\nEstado   : {order['status']}"
        self.order_text.setHtml(
            f'<span style="color:{hc}; font-weight:bold;">{header}</span>'
            f'<br><span style="color:#a0c0a0;">'
            f'{reason}{order_line.replace(chr(10), "<br>")}</span>'
        )

    def _open_config_dialog(self) -> None:
        prefill = self.config.get_credentials() if self.config.has_valid_config() else ("", "")
        dlg = ConfigDialog(self, prefill=prefill)
        if dlg.exec():
            api_key, secret_key = dlg.get_credentials()
            self.config.save_config(api_key, secret_key)
            self.bot = self._build_bot()
            self._set_status("Credenciales guardadas correctamente.")

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tab_main.widget(index)
        if index == 0:
            self._refresh_inicio()
        elif widget is self.portfolio_widget:
            if self.executor:
                self.portfolio_widget.set_executor(self.executor)
            self.portfolio_widget.refresh()
        elif index == 4:
            self._refresh_historial()
        elif index == 5:
            self._refresh_comparacion(fill_actuals=False)

    def _on_chart_timeframe_requested(self, symbol: str, timeframe: str) -> None:
        if timeframe == "Diario":
            result = self._results.get(symbol)
            if result:
                self.chart.update_chart(result["df"], symbol)
        elif timeframe == "1H":
            if not self.bot:
                return
            self._set_status(f"[{symbol}] Cargando datos intraday 1H...")
            try:
                df_intra = self.bot.loader.load_intraday(symbol, days=5)
                self.chart.update_chart(df_intra, symbol)
                self._set_status(f"[{symbol}] Gráfico 1H - ultimos 5 dias de mercado")
            except Exception as exc:
                self._set_status(f"[{symbol}] Error cargando 1H: {exc}", error=True)

    # ══════════════════════════════════════════════════════════════════════
    # PESTANA 4 — COMPARACION  (predicciones vs realidad)
    # ══════════════════════════════════════════════════════════════════════

    def _build_comparacion_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: #0d0d14;")
        root = QVBoxLayout(w)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # ── Cabecera ──────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Comparación: predicciones vs realidad")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #c0c0e0;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._comp_acc_lbl = QLabel("")
        self._comp_acc_lbl.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self._comp_acc_lbl.setStyleSheet("color: #88aacc;")
        hdr.addWidget(self._comp_acc_lbl)

        fill_btn = QPushButton("↻  Rellenar valores reales")
        fill_btn.setFixedHeight(28)
        fill_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        fill_btn.setStyleSheet(
            "QPushButton { background: #1a2a1a; color: #88cc88; border: 1px solid #2a4a2a; "
            "border-radius: 4px; padding: 0 10px; }"
            "QPushButton:hover { background: #00aa44; color: white; }"
        )
        fill_btn.clicked.connect(lambda: self._refresh_comparacion(fill_actuals=True))
        hdr.addWidget(fill_btn)
        root.addLayout(hdr)

        # Nota explicativa
        note = QLabel(
            "Cada dia el modelo hace predicciones. Al pulsar 'Rellenar valores reales' se "
            "descarga el retorno real del siguiente dia de mercado y se calcula el acierto."
        )
        note.setWordWrap(True)
        note.setFont(QFont("Segoe UI", 8))
        note.setStyleSheet("color: #666688;")
        root.addWidget(note)

        # ── Tabla ─────────────────────────────────────────────────────────
        cols = ["Fecha Scan", "Símbolo", "Señal", "Pred. %", "Real %",
                "Fecha Real", "Acerto?", "DA%"]
        self._comp_table = QTableWidget(0, len(cols))
        self._comp_table.setHorizontalHeaderLabels(cols)
        self._comp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._comp_table.horizontalHeader().setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._comp_table.setFont(QFont("Consolas", 9))
        self._comp_table.setAlternatingRowColors(True)
        self._comp_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._comp_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._comp_table.setSortingEnabled(True)
        self._comp_table.setStyleSheet(
            "QTableWidget { background: #0d0d14; alternate-background-color: #12121c; "
            "  color: #c0c0e0; gridline-color: #2a2a3a; }"
            "QHeaderView::section { background: #1a1a28; color: #8888aa; "
            "  border: 1px solid #2a2a3a; padding: 3px; }"
            "QTableWidget::item:selected { background: #0055aa; }"
        )
        root.addWidget(self._comp_table, stretch=1)

        # ── Resumen inferior ──────────────────────────────────────────────
        self._comp_summary_lbl = QLabel("Sin datos de predicciones aun.")
        self._comp_summary_lbl.setFont(QFont("Segoe UI", 8))
        self._comp_summary_lbl.setStyleSheet("color: #666688;")
        root.addWidget(self._comp_summary_lbl)

        return w

    def _fill_actual_returns_bg(self) -> None:
        """Rellena actual_return_pct en predictions_log.csv (corre en hilo separado)."""
        try:
            import pandas as pd
            import yfinance as yf

            if not PREDICTIONS_LOG.exists():
                return
            df = pd.read_csv(PREDICTIONS_LOG, dtype=str)
            if df.empty:
                return

            today = datetime.now().date()
            mask  = df["actual_return_pct"].isna() | (df["actual_return_pct"].str.strip() == "")
            pending_idx = df.index[mask].tolist()
            if not pending_idx:
                return

            changed = False
            for idx in pending_idx:
                try:
                    scan_dt = pd.Timestamp(df.at[idx, "scan_date"])
                    if scan_dt.date() >= today:
                        continue   # todavía hoy — mercado puede no haber cerrado
                    symbol = df.at[idx, "symbol"]
                    pred_pct = float(df.at[idx, "pred_return_pct"].replace("+", ""))
                    start  = str(scan_dt.date())
                    end_dt = scan_dt.date() + timedelta(days=10)
                    hist   = yf.Ticker(symbol).history(
                        start=start, end=str(end_dt), interval="1d", auto_adjust=True
                    )
                    if len(hist) < 2:
                        continue
                    c0 = float(hist["Close"].iloc[0])
                    c1 = float(hist["Close"].iloc[1])
                    actual_ret  = (c1 - c0) / c0 * 100
                    actual_date = hist.index[1].strftime("%Y-%m-%d")
                    dir_correct = "SI" if (pred_pct > 0) == (actual_ret > 0) else "NO"
                    df.at[idx, "actual_return_pct"] = f"{actual_ret:+.2f}"
                    df.at[idx, "actual_date"]        = actual_date
                    df.at[idx, "direction_correct"]  = dir_correct
                    changed = True
                except Exception:
                    pass

            if changed:
                df.to_csv(PREDICTIONS_LOG, index=False)
        except Exception:
            pass

    def _refresh_comparacion(self, fill_actuals: bool = False) -> None:
        if fill_actuals:
            self._set_status("Descargando retornos reales de mercado...")
            t = threading.Thread(target=self._fill_actuals_then_refresh, daemon=True)
            t.start()
        else:
            self._load_comparacion_table()

    def _fill_actuals_then_refresh(self) -> None:
        self._fill_actual_returns_bg()
        # Volver al hilo principal via QTimer one-shot (no podemos tocar Qt desde hilo)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._load_comparacion_table)

    def _load_comparacion_table(self) -> None:
        try:
            import pandas as pd
        except ImportError:
            return

        self._comp_table.setSortingEnabled(False)
        self._comp_table.setRowCount(0)

        if not PREDICTIONS_LOG.exists():
            self._comp_summary_lbl.setText("No hay predicciones registradas aun. Lanza un scan para empezar.")
            self._comp_acc_lbl.setText("")
            self._set_status("Sin predictions_log.csv todavia.")
            return

        try:
            df = pd.read_csv(PREDICTIONS_LOG, dtype=str).fillna("")
        except Exception as e:
            self._comp_summary_lbl.setText(f"Error leyendo predictions_log.csv: {e}")
            self._set_status(f"Error en Comparación: {e}", error=True)
            return

        if df.empty:
            self._comp_summary_lbl.setText("El fichero de predicciones esta vacio.")
            return

        # Ordenar por fecha descendente
        df["_ts"] = pd.to_datetime(df["scan_date"], errors="coerce")
        df = df.sort_values("_ts", ascending=False).reset_index(drop=True)

        self._comp_table.setRowCount(len(df))
        n_compared = 0
        n_correct  = 0

        for row, rec in df.iterrows():
            signal    = rec.get("signal", "")
            pred_pct  = rec.get("pred_return_pct", "")
            real_pct  = rec.get("actual_return_pct", "")
            dir_ok    = rec.get("direction_correct", "")

            # Color de señal
            if "COMPRAR" in signal:
                sig_color = "#00cc88"
            elif "VENDER" in signal:
                sig_color = "#ff4455"
            else:
                sig_color = "#ffaa00"

            # Color retorno real
            try:
                real_f = float(real_pct.replace("+", "")) if real_pct else None
                real_color = "#00cc88" if real_f and real_f > 0 else "#ff4455" if real_f and real_f < 0 else "#888888"
            except Exception:
                real_f = None
                real_color = "#888888"

            # Color acierto
            if dir_ok == "SI":
                ok_color = "#00cc88"
                n_correct += 1
                n_compared += 1
            elif dir_ok == "NO":
                ok_color = "#ff4455"
                n_compared += 1
            else:
                ok_color = "#666688"

            def cell(text: str, color: str | None = None) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if color:
                    it.setForeground(QColor(color))
                return it

            scan_str = rec.get("scan_date", "")[:16]   # trim seconds
            self._comp_table.setItem(row, 0, cell(scan_str))
            self._comp_table.setItem(row, 1, cell(rec.get("symbol", ""), "#ffffff"))
            self._comp_table.setItem(row, 2, cell(signal, sig_color))
            self._comp_table.setItem(row, 3, _SortItem(pred_pct, float(pred_pct.replace("+", "") or 0)))
            self._comp_table.setItem(row, 4, _SortItem(real_pct if real_pct else "—",
                                                        real_f if real_f is not None else 0.0))
            self._comp_table.item(row, 4).setForeground(QColor(real_color))
            self._comp_table.setItem(row, 5, cell(rec.get("actual_date", "—")))
            self._comp_table.setItem(row, 6, cell(dir_ok if dir_ok else "pendiente", ok_color))
            self._comp_table.setItem(row, 7, _SortItem(
                rec.get("da_pct", ""), float(rec.get("da_pct", "0") or 0)
            ))

        self._comp_table.setSortingEnabled(True)

        # Resumen
        total_preds = len(df)
        if n_compared > 0:
            pct_ok = n_correct / n_compared * 100
            color  = "#00cc88" if pct_ok >= 55 else "#ffaa00" if pct_ok >= 50 else "#ff4455"
            self._comp_acc_lbl.setText(f"Precisión: {pct_ok:.0f}%  ({n_correct}/{n_compared})")
            self._comp_acc_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            pending = total_preds - n_compared
            pending_txt = f"  |  {pending} pendientes de datos reales" if pending > 0 else ""
            self._comp_summary_lbl.setText(
                f"{total_preds} predicciones en total  |  "
                f"Comparadas: {n_compared}  |  Acertadas: {n_correct} ({pct_ok:.0f}%)"
                f"{pending_txt}"
            )
            self._set_status(f"Comparación actualizada — precision {pct_ok:.0f}% ({n_correct}/{n_compared})")
        else:
            self._comp_acc_lbl.setText("Sin datos reales aun")
            self._comp_acc_lbl.setStyleSheet("color: #666688;")
            self._comp_summary_lbl.setText(
                f"{total_preds} predicciones registradas — pulsa 'Rellenar valores reales' para comparar."
            )
            self._set_status("Comparación: pulsa 'Rellenar valores reales' para descargar datos de mercado.")

    # ══════════════════════════════════════════════════════════════════════

    def _set_status(self, msg: str, error: bool = False) -> None:
        if not hasattr(self, "status_bar"):
            return
        color = "#ff6677" if error else "#88aacc"
        self.status_bar.setText(msg)
        self.status_bar.setStyleSheet(
            f"QLineEdit {{ background: #0a0a12; border: none; border-top: 1px solid #2a2a3a;"
            f" color: {color}; padding: 0 8px; }}"
        )
