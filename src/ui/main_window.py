import csv
import os
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox,
    QFrame, QTextEdit, QSplitter, QStatusBar,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMenuBar, QMenu, QCheckBox, QTabWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QAction, QColor

from src.config.config_manager import ConfigManager
from src.data.data_loader import DataLoader
from src.data.sp100 import SP100_SYMBOLS
from src.analysis.trading_bot import TradingBot
from src.trading.order_executor import OrderExecutor
from src.ui.chart_widget import ChartWidget
from src.ui.config_dialog import ConfigDialog
from src.ui.backtest_widget import BacktestWidget
from src.ui.portfolio_widget import PortfolioWidget

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR    = PROJECT_ROOT / "models"
CACHE_DIR    = PROJECT_ROOT / "data_cache"


# ── Traducción de errores comunes al español ──────────────────────────────
def _traducir_error(exc: Exception) -> str:
    tipo = type(exc).__name__
    msg  = str(exc)

    if "not found" in msg.lower() or "no data" in msg.lower() or "no devolvió" in msg.lower():
        return f"Símbolo no encontrado o sin datos. Comprueba que el ticker sea correcto."
    if "barras disponibles" in msg or "Solo" in msg:
        return msg
    if "ConnectionError" in tipo or "connect" in msg.lower():
        return "Error de conexión. Comprueba tu conexión a Internet."
    if "Unauthorized" in msg or "403" in msg or "401" in msg:
        return "Credenciales de API incorrectas o caducadas. Ve a Configuración → Editar API Keys."
    if "RateLimitError" in tipo or "429" in msg:
        return "Demasiadas peticiones. Espera unos segundos e inténtalo de nuevo."
    if "ValueError" in tipo:
        return f"Error en los datos: {msg}"
    if "KeyError" in tipo:
        return f"Campo no encontrado en los datos: {msg}"
    return f"{tipo}: {msg}"


# ── Worker multi-símbolo ───────────────────────────────────────────────────
class MultiSymbolWorker(QObject):
    symbol_done  = pyqtSignal(dict)
    symbol_error = pyqtSignal(str, str)   # (símbolo, mensaje)
    progress     = pyqtSignal(str)
    all_done     = pyqtSignal()

    def __init__(self, bot: TradingBot, symbols: list[str], start_date: str,
                 return_threshold: float = 0.0):
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


# ── Worker de ejecución de órdenes ────────────────────────────────────────
class OrderWorker(QObject):
    order_done = pyqtSignal(str, dict)   # (symbol, exec_result)

    def __init__(
        self,
        executor: OrderExecutor,
        symbol: str,
        signal: str,
        pred_return: float,
        quote: dict,
        metrics: dict,
        trade_amount: float,
        backtest_metrics: dict | None = None,
    ):
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


# ── Ventana principal ──────────────────────────────────────────────────────
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

        self.setWindowTitle("AlgoTrader — XGBoost + Alpaca Paper Trading")
        self.setMinimumSize(1260, 860)
        self._build_menu()
        self._build_ui()
        self._set_status("Listo. Ingresa símbolos separados por coma y pulsa Entrenar y Analizar.")

    # ── Construcción de la UI ──────────────────────────────────────────────

    def _build_menu(self) -> None:
        cfg_menu = self.menuBar().addMenu("Configuración")
        edit_keys = QAction("Editar API Keys…", self)
        edit_keys.triggered.connect(self._open_config_dialog)
        cfg_menu.addAction(edit_keys)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        # ── Toolbar ────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        toolbar.addWidget(QLabel("Símbolo(s):"))
        self.symbol_input = QLineEdit("AAPL")
        self.symbol_input.setFixedHeight(32)
        self.symbol_input.setPlaceholderText("AAPL, TSLA, NVDA…")
        self.symbol_input.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.symbol_input.setMinimumWidth(220)
        toolbar.addWidget(self.symbol_input)

        toolbar.addWidget(QLabel("Desde:"))
        self.start_date_input = QLineEdit("2010-01-01")
        self.start_date_input.setFixedWidth(100)
        self.start_date_input.setFixedHeight(32)
        self.start_date_input.setFont(QFont("Consolas", 9))
        self.start_date_input.setToolTip(
            "Fecha de inicio del historial (YYYY-MM-DD).\n"
            "Cuantos más años, mejor aprende el modelo.\n"
            "Yahoo Finance cubre desde ~1993 para grandes índices."
        )
        toolbar.addWidget(self.start_date_input)

        toolbar.addStretch()

        self.auto_exec_check = QCheckBox("Auto-ejecutar")
        self.auto_exec_check.setToolTip(
            "Ejecuta órdenes automáticamente en Alpaca Paper Trading\n"
            "tras el análisis. Solo actúa en señales fuertes\n"
            "(COMPRAR prob≥65% o VENDER prob≤35%) con modelo confiable (CV≥55%)."
        )
        self.auto_exec_check.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.auto_exec_check.setStyleSheet(
            "QCheckBox { color: #ffffff; spacing: 6px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #5588aa; border-radius: 3px; background: #12121c; }"
            "QCheckBox::indicator:checked { background: #0077cc; border-color: #0099ff; }"
            "QCheckBox::indicator:hover { border-color: #0099ff; }"
        )
        toolbar.addWidget(self.auto_exec_check)

        toolbar.addWidget(QLabel("$ por op:"))
        self.trade_amount_input = QLineEdit("1000")
        self.trade_amount_input.setFixedWidth(75)
        self.trade_amount_input.setFixedHeight(32)
        self.trade_amount_input.setFont(QFont("Consolas", 9))
        self.trade_amount_input.setToolTip(
            "Monto máximo en dólares por operación.\n"
            "Con Kelly activo se usa como techo, no como monto fijo."
        )
        toolbar.addWidget(self.trade_amount_input)

        toolbar.addWidget(QLabel("Umbral ret.:"))
        self.threshold_input = QLineEdit("0.0")
        self.threshold_input.setFixedWidth(52)
        self.threshold_input.setFixedHeight(32)
        self.threshold_input.setFont(QFont("Consolas", 9))
        self.threshold_input.setToolTip(
            "Retorno mínimo (%) para etiquetar una barra como COMPRA en entrenamiento.\n"
            "0.0 → cualquier subida (más señales, menos precisas)\n"
            "0.5 → solo sube >0.5% (menos señales, más selectivo)\n"
            "1.0 → solo sube >1.0% (muy selectivo)"
        )
        toolbar.addWidget(self.threshold_input)
        toolbar.addWidget(QLabel("%"))

        self.scan_btn = QPushButton("🔍  Escanear S&P100")
        self.scan_btn.setFixedHeight(36)
        self.scan_btn.setFixedWidth(185)
        self.scan_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.scan_btn.setStyleSheet(
            "QPushButton { background: #7733cc; color: white; border-radius: 5px; }"
            "QPushButton:hover { background: #9955ff; }"
            "QPushButton:disabled { background: #333355; color: #666688; }"
        )
        self.scan_btn.setToolTip(
            f"Analiza los {len(SP100_SYMBOLS)} símbolos del S&P100 y filtra\n"
            "solo los que tienen señal fuerte (COMPRAR/VENDER).\n"
            "Con caché activo tarda ~2-5 min. Sin caché puede tardar más."
        )
        self.scan_btn.clicked.connect(self._run_scan)
        toolbar.addWidget(self.scan_btn)

        self.train_btn = QPushButton("▶  Entrenar y Analizar")
        self.train_btn.setFixedHeight(36)
        self.train_btn.setFixedWidth(210)
        self.train_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.train_btn.setStyleSheet(
            "QPushButton { background: #0077cc; color: white; border-radius: 5px; }"
            "QPushButton:hover { background: #0099ff; }"
            "QPushButton:disabled { background: #333355; color: #666688; }"
        )
        self.train_btn.clicked.connect(self._run_analysis)
        toolbar.addWidget(self.train_btn)

        root.addLayout(toolbar)

        # ── Tabla comparativa ──────────────────────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Símbolo", "Señal", "Ret. Esperado", "Ask", "Bid", "Dir. Accuracy", "Estado"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.table.setFont(QFont("Consolas", 9))
        self.table.setMinimumHeight(60)
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

        # ── Barra de detalle (mensaje completo, seleccionable) ─────────────
        self.detail_line = QLineEdit()
        self.detail_line.setReadOnly(True)
        self.detail_line.setPlaceholderText("Haz clic en una fila para ver el mensaje completo…")
        self.detail_line.setFont(QFont("Consolas", 9))
        self.detail_line.setFixedHeight(26)
        self.detail_line.setStyleSheet(
            "QLineEdit { background: #0d0d14; color: #c0c0e0; border: 1px solid #2a2a3a; "
            "border-radius: 3px; padding: 0 6px; }"
        )

        # Contenedor tabla + detalle (parte superior del splitter principal)
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        top_layout.addWidget(self.table, stretch=1)
        top_layout.addWidget(self.detail_line)

        # ── Gráfico + panel explicación (sub-splitter vertical) ────────────
        self.chart = ChartWidget()
        self.chart.bar_clicked.connect(self._on_bar_clicked)
        self.chart.timeframe_requested.connect(self._on_chart_timeframe_requested)

        self.explain_text = QTextEdit()
        self.explain_text.setReadOnly(True)
        self.explain_text.setFont(QFont("Consolas", 9))
        self.explain_text.setMinimumHeight(1)
        self.explain_text.setPlaceholderText("Haz clic en cualquier vela del gráfico para ver el análisis de ese momento…")
        self.explain_text.setStyleSheet(
            "QTextEdit { background: #090d12; border: 1px solid #1a2a1a; "
            "color: #b0d0b0; border-radius: 4px; padding: 6px; }"
        )

        splitter_chart = QSplitter(Qt.Orientation.Vertical)
        splitter_chart.addWidget(self.chart)
        splitter_chart.addWidget(self.explain_text)
        splitter_chart.setSizes([500, 120])
        splitter_chart.setCollapsible(0, False)
        splitter_chart.setCollapsible(1, True)

        # ── Splitter horizontal: gráfico | panel derecho ───────────────────
        splitter_h = QSplitter(Qt.Orientation.Horizontal)
        splitter_h.addWidget(splitter_chart)
        right_panel = self._build_right_panel()
        splitter_h.addWidget(right_panel)
        splitter_h.setSizes([820, 360])
        splitter_h.setStretchFactor(0, 1)
        splitter_h.setCollapsible(1, True)

        # ── Pestañas: Análisis / Backtest OOS / Portfolio ─────────────────
        self.backtest_widget  = BacktestWidget()
        self.portfolio_widget = PortfolioWidget(
            executor=self.executor,
            project_root=PROJECT_ROOT,
        )

        self.tab_main = QTabWidget()
        self.tab_main.setStyleSheet("""
            QTabWidget::pane  { border: 1px solid #2a2a3a; }
            QTabBar::tab      { background: #1a1a28; color: #8888aa;
                                padding: 6px 18px; border: 1px solid #2a2a3a;
                                border-bottom: none; margin-right: 2px; }
            QTabBar::tab:selected { background: #0d0d14; color: #c0c0e0; }
            QTabBar::tab:hover    { background: #2a2a3a; color: #c0c0e0; }
        """)
        self.tab_main.addTab(splitter_h,             "Análisis")
        self.tab_main.addTab(self.backtest_widget,   "Backtest OOS")
        self.tab_main.addTab(self.portfolio_widget,  "Portfolio")
        self.tab_main.currentChanged.connect(self._on_tab_changed)

        # ── Splitter principal vertical: lista símbolos | área gráfico ──────
        _handle_style = (
            "QSplitter::handle { background: #2a2a3a; }"
            "QSplitter::handle:vertical { height: 6px; }"
            "QSplitter::handle:horizontal { width: 6px; }"
            "QSplitter::handle:hover { background: #0077cc; }"
        )
        splitter_v = QSplitter(Qt.Orientation.Vertical)
        splitter_v.setStyleSheet(_handle_style)
        splitter_h.setStyleSheet(_handle_style)
        splitter_chart.setStyleSheet(_handle_style)
        splitter_v.addWidget(top_widget)
        splitter_v.addWidget(self.tab_main)
        splitter_v.setSizes([180, 640])
        splitter_v.setStretchFactor(1, 1)
        splitter_v.setCollapsible(0, True)
        splitter_v.setCollapsible(1, False)
        root.addWidget(splitter_v, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_right_panel(self) -> QSplitter:
        panel = QSplitter(Qt.Orientation.Vertical)
        panel.setMinimumWidth(220)

        # ── Sección: Señal ─────────────────────────────────────────────────
        signal_frame = QFrame()
        signal_frame.setFrameShape(QFrame.Shape.StyledPanel)
        signal_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        sf = QVBoxLayout(signal_frame)
        sf.setSpacing(6)
        sf.setContentsMargins(14, 12, 14, 12)

        self.signal_label = QLabel("—")
        self.signal_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sf.addWidget(self.signal_label)

        self.prob_label = QLabel("Retorno esperado: —")
        self.prob_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prob_label.setFont(QFont("Segoe UI", 11))
        sf.addWidget(self.prob_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a3a;")
        sf.addWidget(sep)

        self.ask_label       = QLabel("Ask: —")
        self.bid_label       = QLabel("Bid: —")
        self.suggest_label   = QLabel("Sugerencia: —")
        self.suggest_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        self.sentiment_label = QLabel("Sentimiento: —")
        self.sentiment_label.setFont(QFont("Consolas", 9))
        self.options_label   = QLabel("Put/Call ratio: —")
        self.options_label.setFont(QFont("Consolas", 9))
        for lbl in (self.ask_label, self.bid_label, self.suggest_label,
                    self.sentiment_label, self.options_label):
            lbl.setFont(QFont("Consolas", 10))
            sf.addWidget(lbl)

        panel.addWidget(signal_frame)

        # ── Sección: Métricas ──────────────────────────────────────────────
        mf = QFrame()
        mf.setFrameShape(QFrame.Shape.StyledPanel)
        mf.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        ml = QVBoxLayout(mf)
        ml.setContentsMargins(14, 10, 14, 10)
        t = QLabel("Métricas del Modelo (XGBoost)")
        t.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        t.setStyleSheet("color: #8888aa;")
        ml.addWidget(t)
        self.metrics_text = QTextEdit()
        self.metrics_text.setReadOnly(True)
        self.metrics_text.setFont(QFont("Consolas", 9))
        self.metrics_text.setMinimumHeight(1)
        self.metrics_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; }"
        )
        ml.addWidget(self.metrics_text)
        panel.addWidget(mf)

        # ── Sección: Feature importance ────────────────────────────────────
        imf = QFrame()
        imf.setFrameShape(QFrame.Shape.StyledPanel)
        imf.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        il = QVBoxLayout(imf)
        il.setContentsMargins(14, 10, 14, 10)
        it = QLabel("Top Features (importancia XGBoost)")
        it.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        it.setStyleSheet("color: #8888aa;")
        il.addWidget(it)
        self.importance_text = QTextEdit()
        self.importance_text.setReadOnly(True)
        self.importance_text.setFont(QFont("Consolas", 9))
        self.importance_text.setMinimumHeight(1)
        self.importance_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; }"
        )
        il.addWidget(self.importance_text)
        panel.addWidget(imf)

        # ── Sección: Ejecución de órdenes ──────────────────────────────────
        orf = QFrame()
        orf.setFrameShape(QFrame.Shape.StyledPanel)
        orf.setStyleSheet(
            "QFrame { background: #0e1218; border: 1px solid #2a3a2a; border-radius: 8px; }"
        )
        orl = QVBoxLayout(orf)
        orl.setContentsMargins(14, 10, 14, 10)
        ort = QLabel("Ejecución automática (Paper Trading)")
        ort.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        ort.setStyleSheet("color: #6aaa6a;")
        orl.addWidget(ort)
        self.order_text = QTextEdit()
        self.order_text.setReadOnly(True)
        self.order_text.setFont(QFont("Consolas", 9))
        self.order_text.setMinimumHeight(1)
        self.order_text.setStyleSheet(
            "QTextEdit { background: #090d0d; border: none; color: #a0c0a0; }"
        )
        self.order_text.setPlaceholderText("Sin órdenes ejecutadas aún…")
        orl.addWidget(self.order_text)
        panel.addWidget(orf)

        panel.setSizes([180, 150, 150, 100])
        for i in range(panel.count()):
            panel.setCollapsible(i, True)

        return panel

    # ── Lógica ────────────────────────────────────────────────────────────

    def _build_bot(self) -> TradingBot | None:
        if self.config.has_valid_config():
            api_key, secret_key = self.config.get_credentials()
            loader = DataLoader(api_key, secret_key, cache_dir=CACHE_DIR)
            self.executor = OrderExecutor(api_key, secret_key, base_url=self.config.get_base_url())
            return TradingBot(loader, model_dir=MODEL_DIR)
        self.executor = None
        return None

    def _parse_symbols(self) -> list[str]:
        raw = self.symbol_input.text()
        return [s.strip().upper() for s in raw.split(",") if s.strip()]

    def _parse_threshold(self) -> float:
        try:
            val = float(self.threshold_input.text().strip())
            return max(0.0, min(val / 100.0, 0.05))  # clamp 0–5%
        except ValueError:
            return 0.0

    def _parse_start_date(self) -> str:
        raw = self.start_date_input.text().strip()
        # Validación básica de formato
        try:
            from datetime import datetime
            datetime.strptime(raw, "%Y-%m-%d")
            return raw
        except ValueError:
            return "2010-01-01"

    def _run_scan(self) -> None:
        self._run_analysis(symbols=list(SP100_SYMBOLS), scan_mode=True)

    def _run_analysis(
        self,
        symbols:   list[str] | None = None,
        scan_mode: bool = False,
    ) -> None:
        if not self.bot:
            self._open_config_dialog()
            return

        self._scan_mode = scan_mode

        if symbols is None:
            symbols = self._parse_symbols()
        if not symbols:
            self._set_status("Error: introduce al menos un símbolo válido.", error=True)
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
        self.table.setRowHidden  # asegurar que no hay filas ocultas del escaneo anterior
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, False)
        self.table.setRowCount(len(symbols))
        for row, sym in enumerate(symbols):
            self._set_table_row(row, sym, estado="En proceso…")

        if scan_mode:
            self._set_status(
                f"Iniciando escaneo de {len(symbols)} símbolos S&P100 "
                "(los modelos cacheados de hoy no reentrenan)…"
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
        def cell(text, color=None, bold=False, center=False):
            item = QTableWidgetItem(text)
            if color:
                item.setForeground(QColor(color))
            if bold:
                item.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            if center:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return item

        self.table.setItem(row, 0, cell(symbol, "#ffffff", bold=True, center=True))

        if result:
            signal      = result["signal"]
            pred_return = result["pred_return"]
            quote       = result["quote"]
            m           = result["metrics"]

            sig_color = (
                "#00cc88" if "COMPRAR" in signal else
                "#ff4455" if "VENDER"  in signal else
                "#ffaa00"
            )
            ret_color = "#00cc88" if pred_return >= 0 else "#ff4455"
            self.table.setItem(row, 1, cell(signal, sig_color, bold=True, center=True))
            self.table.setItem(row, 2, cell(f"{pred_return*100:+.2f}%", ret_color, center=True))
            self.table.setItem(row, 3, cell(f"${quote['ask_price']:.4f}", center=True))
            self.table.setItem(row, 4, cell(f"${quote['bid_price']:.4f}", center=True))
            self.table.setItem(row, 5, cell(
                f"{m.get('oos_dir_acc', 0)*100:.1f}%",
                center=True
            ))
            self.table.setItem(row, 6, cell("Completado ✓", "#00cc88", center=True))

        elif error:
            for col in range(1, 6):
                it = cell("—", "#666688", center=True)
                it.setToolTip(error)
                self.table.setItem(row, col, it)
            err_item = cell(f"Error: {error[:60]}", "#ff6677", center=True)
            err_item.setToolTip(error)
            self.table.setItem(row, 6, err_item)

        else:
            for col in range(1, 6):
                self.table.setItem(row, col, cell("—", "#666688", center=True))
            self.table.setItem(row, 6, cell(estado, "#ffaa00", center=True))

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

        self._update_detail_panel(result)

        if result.get("backtest"):
            self._backtest_results[symbol] = result["backtest"]
            self.backtest_widget.update(result["backtest"], symbol)

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
                f"Escaneo S&P100 completado — {n_strong} señales fuertes "
                f"de {exitosos} analizados ({fallidos} errores)"
            )
        elif exitosos == 0:
            self._set_status("Análisis completado — todos los símbolos fallaron.", error=True)
        elif fallidos > 0:
            self._set_status(
                f"Análisis completado — {exitosos} OK, {fallidos} con error."
            )
        else:
            self._set_status(f"Análisis completado — {', '.join(self._results.keys())}")

        self.table.setSortingEnabled(True)

    def _filter_scan_results(self) -> int:
        """Oculta filas NEUTRAL. Devuelve el número de señales fuertes (sin débil)."""
        n_strong = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                self.table.setRowHidden(row, True)
                continue
            symbol = item.text()
            result = self._results.get(symbol)
            if result:
                signal = result["signal"]
                visible = signal != "NEUTRAL"
                self.table.setRowHidden(row, not visible)
                if visible and "débil" not in signal:
                    n_strong += 1
            else:
                self.table.setRowHidden(row, True)
        return n_strong

    def _export_scan_log(self) -> None:
        """Exporta todas las señales no-neutral del escaneo a scan_log.csv."""
        log_path  = PROJECT_ROOT / "scan_log.csv"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []
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

    def _send_telegram_scan_alert(self, n_strong: int) -> None:
        """Envía alerta Telegram si TELEGRAM_TOKEN y TELEGRAM_CHAT_ID están en .env."""
        token   = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        try:
            from src.notifications.telegram_notifier import send_alert
            strong = [
                (sym, r) for sym, r in self._results.items()
                if r["signal"] in ("COMPRAR", "VENDER")
            ]
            weak = [
                (sym, r) for sym, r in self._results.items()
                if "débil" in r["signal"]
            ]
            lines = [
                f"🔍 <b>AlgoTrader — Scan S&P100</b>  "
                f"{datetime.now().strftime('%d/%m %H:%M')}"
            ]
            if strong:
                lines.append(f"\n<b>{len(strong)} señales fuertes:</b>")
                for sym, r in strong[:10]:
                    icon = "✅" if "COMPRAR" in r["signal"] else "🔴"
                    ret  = r["pred_return"] * 100
                    lines.append(f"• <b>{sym}</b> {icon} {r['signal']}  {ret:+.2f}%")
            if weak:
                syms = ", ".join(sym for sym, _ in weak[:6])
                lines.append(f"\n<i>{len(weak)} débiles: {syms}</i>")
            if not strong and not weak:
                lines.append("\nSin señales esta sesión.")
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
        df          = result["df"]
        symbol      = result["symbol"]
        signal      = result["signal"]
        pred_return = result["pred_return"]
        metrics     = result["metrics"]
        quote       = result["quote"]
        imp         = result["importance"]
        sentiment   = result.get("sentiment", {})
        options     = result.get("options", {})

        self.chart.update_chart(df, symbol, reset_tf=True)

        color = (
            "#00cc88" if "COMPRAR" in signal else
            "#ff4455" if "VENDER"  in signal else
            "#ffaa00"
        )
        self.signal_label.setText(signal)
        self.signal_label.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: bold;"
        )

        ret_color = "#00cc88" if pred_return >= 0 else "#ff4455"
        self.prob_label.setText(
            f'Retorno esperado: <b style="color:{ret_color}">{pred_return*100:+.2f}%</b>'
        )
        self.prob_label.setTextFormat(Qt.TextFormat.RichText)

        ask = quote["ask_price"]
        bid = quote["bid_price"]
        self.ask_label.setText(f"Ask: ${ask:.4f}  ({quote['ask_size']} acc.)")
        self.bid_label.setText(f"Bid: ${bid:.4f}  ({quote['bid_size']} acc.)")

        if "COMPRAR" in signal:
            self.suggest_label.setText(f"Compra límite sugerida: ${bid + 0.01:.4f}")
        elif "VENDER" in signal:
            self.suggest_label.setText(f"Venta límite sugerida:  ${ask - 0.01:.4f}")
        else:
            self.suggest_label.setText("Sin señal clara — esperar confirmación")

        # Sentimiento de noticias
        sent_score = sentiment.get("sentiment_score", 0.0)
        sent_vol   = sentiment.get("sentiment_volume", 0)
        if sent_vol > 0:
            sent_txt = (
                "positivo" if sent_score > 0.15 else
                "negativo" if sent_score < -0.15 else "neutro"
            )
            self.sentiment_label.setText(
                f"Sentimiento: {sent_txt} ({sent_score:+.2f}, {sent_vol} noticias)"
            )
            sent_color = (
                "#00cc88" if sent_score > 0.15 else
                "#ff4455" if sent_score < -0.15 else "#aaaaaa"
            )
            self.sentiment_label.setStyleSheet(f"color: {sent_color};")
        else:
            self.sentiment_label.setText("Sentimiento: sin noticias recientes")
            self.sentiment_label.setStyleSheet("color: #666688;")

        # Put/call ratio
        pc = options.get("pc_ratio", 1.0)
        pc_interp = (
            "presión bajista" if pc > 1.5 else
            "presión alcista" if pc < 0.7 else "neutral"
        )
        self.options_label.setText(f"Put/Call ratio: {pc:.2f}  ({pc_interp})")
        pc_color = (
            "#ff4455" if pc > 1.5 else
            "#00cc88" if pc < 0.7 else "#aaaaaa"
        )
        self.options_label.setStyleSheet(f"color: {pc_color};")

        m = metrics
        self.metrics_text.setPlainText(
            f"IC OOS         : {m.get('oos_ic', 0)*100:.2f}%\n"
            f"Dir. Accuracy  : {m.get('oos_dir_acc', 0)*100:.1f}%\n"
            f"MAE OOS        : {m.get('oos_mae', 0)*100:.3f}%\n"
            f"Muestras       : {m.get('n_samples', 0)}  "
            f"(positivos: {m.get('n_positive', 0)})"
        )

        lines = [f"{name:<16} {score*100:>5.1f}%" for name, score in list(imp.items())[:8]]
        self.importance_text.setPlainText("\n".join(lines))

    def _reset_signal_panel(self) -> None:
        self.signal_label.setText("…")
        self.signal_label.setStyleSheet("color: #666688;")
        self.prob_label.setText("Probabilidad de subida: —")
        self.ask_label.setText("Ask: —")
        self.bid_label.setText("Bid: —")
        self.suggest_label.setText("Sugerencia: —")
        self.metrics_text.clear()
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
        chg     = (c - o) / o * 100 if o > 0 else 0
        arrow   = "▲" if chg >= 0 else "▼"
        vela    = "Alcista  (cierre > apertura)" if c >= o else "Bajista  (cierre < apertura)"
        rango   = (h - l) / c * 100 if c > 0 else 0

        lines = [
            f"── {symbol}  {date_str} ──────────────────",
            "",
            "PRECIO",
            f"  Apertura : ${o:>10.2f}",
            f"  Cierre   : ${c:>10.2f}   {arrow} {abs(chg):.2f}%",
            f"  Máximo   : ${h:>10.2f}",
            f"  Mínimo   : ${l:>10.2f}",
            f"  Rango    :  {rango:.2f}% del precio",
            f"  Tipo     :  {vela}",
            "",
        ]

        # Volumen
        vol     = row.get("volume", 0)
        vol_sma = row.get("vol_sma20", None)
        if vol and vol > 0:
            v_str = f"{vol/1e6:.2f}M" if vol >= 1e6 else f"{vol:,.0f}"
            if vol_sma and not math.isnan(float(vol_sma)) and vol_sma > 0:
                ratio = vol / vol_sma
                if ratio > 1.5:
                    interp = "Muy elevado — movimiento con fuerte convicción"
                elif ratio > 1.1:
                    interp = "Sobre la media — confirma la dirección"
                elif ratio < 0.7:
                    interp = "Bajo — movimiento débil, poca convicción"
                else:
                    interp = "Normal — sin señal de volumen adicional"
                lines += [f"VOLUMEN  {v_str}  ({ratio:.1f}× SMA20)", f"  → {interp}", ""]
            else:
                lines += [f"VOLUMEN  {v_str}", ""]

        # RSI
        rsi = row.get("rsi", None)
        if rsi is not None and not math.isnan(float(rsi)):
            rsi = float(rsi)
            if   rsi >= 80: interp = "Sobrecompra extrema — alta probabilidad de corrección"
            elif rsi >= 70: interp = "Sobrecompra — vigilar posible giro bajista"
            elif rsi >= 60: interp = "Zona alcista fuerte"
            elif rsi >= 40: interp = "Zona neutral — sin sesgo claro"
            elif rsi >= 30: interp = "Zona bajista moderada"
            elif rsi >= 20: interp = "Sobreventa — posible rebote alcista"
            else:           interp = "Sobreventa extrema — rebote muy probable"
            lines += [f"RSI (14)   {rsi:.1f}", f"  → {interp}", ""]

        # Bollinger Bands
        bb_u = row.get("bb_upper", None)
        bb_l = row.get("bb_lower", None)
        if bb_u is not None and bb_l is not None:
            try:
                bb_u, bb_l = float(bb_u), float(bb_l)
                if not math.isnan(bb_u) and bb_u > bb_l > 0:
                    pct = (c - bb_l) / (bb_u - bb_l) * 100
                    if   pct >= 95: interp = "Rompiendo banda superior — sobreextensión"
                    elif pct >= 75: interp = "Cerca de banda superior — presión alcista"
                    elif pct <= 5:  interp = "Rompiendo banda inferior — sobreextensión"
                    elif pct <= 25: interp = "Cerca de banda inferior — presión bajista"
                    else:           interp = "Dentro del canal — consolidación"
                    lines += [
                        f"BOLLINGER  {pct:.0f}% del canal",
                        f"  Sup: ${bb_u:.2f}  |  Inf: ${bb_l:.2f}",
                        f"  → {interp}", "",
                    ]
            except (TypeError, ValueError):
                pass

        # SMAs
        sma20 = row.get("sma20", None)
        sma50 = row.get("sma50", None)
        sma_lines = []
        for label, val in [("SMA20", sma20), ("SMA50", sma50)]:
            if val is not None:
                try:
                    val = float(val)
                    if not math.isnan(val) and val > 0:
                        diff = (c - val) / val * 100
                        sign = "+" if diff >= 0 else ""
                        pos  = "por encima" if diff >= 0 else "por debajo"
                        sma_lines.append(f"  {label}: ${val:.2f}  ({sign}{diff:.1f}% — precio {pos})")
                except (TypeError, ValueError):
                    pass
        if sma_lines:
            lines += ["MEDIAS MÓVILES"] + sma_lines + [""]

        # MACD
        macd    = row.get("macd",        None)
        macd_s  = row.get("macd_signal", None)
        macd_h  = row.get("macd_hist",   None)
        if macd is not None and macd_s is not None:
            try:
                macd, macd_s = float(macd), float(macd_s)
                if not math.isnan(macd) and not math.isnan(macd_s):
                    if macd > macd_s:
                        interp = "MACD sobre señal → momentum alcista"
                    else:
                        interp = "MACD bajo señal → momentum bajista"
                    h_str = f"{float(macd_h):+.4f}" if macd_h is not None else "—"
                    lines += [
                        f"MACD  {macd:+.4f} | Señal: {macd_s:+.4f} | Hist: {h_str}",
                        f"  → {interp}", "",
                    ]
            except (TypeError, ValueError):
                pass

        lines.append(f"Barra {data['bar_idx'] + 1} de {data['n_bars']} mostradas")
        return "\n".join(lines)

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
        thread.finished.connect(lambda t=thread: self._order_threads.remove(t) if t in self._order_threads else None)
        thread.start()
        self._order_threads.append(thread)

    def _on_order_done(self, symbol: str, exec_result: dict) -> None:
        self._order_results[symbol] = exec_result
        self._update_order_panel(symbol, exec_result)

        action = exec_result["action"]
        reason = exec_result["reason"]
        if action == "buy":
            self._set_status(f"[{symbol}] COMPRA ejecutada — {reason}")
            self._log_order_csv(symbol, exec_result)
        elif action == "sell":
            self._set_status(f"[{symbol}] VENTA ejecutada — {reason}")
            self._log_order_csv(symbol, exec_result)
        elif action == "error":
            self._set_status(f"[{symbol}] Error en orden — {reason}", error=True)
        else:
            self._set_status(f"[{symbol}] Orden omitida — {reason}")

    def _log_order_csv(self, symbol: str, exec_result: dict) -> None:
        log_path  = PROJECT_ROOT / "orders_log.csv"
        order     = exec_result.get("order") or {}
        reason    = exec_result.get("reason", "")
        analysis  = self._results.get(symbol, {})
        metrics   = analysis.get("metrics", {})

        qty         = order.get("qty", "")
        limit_price = order.get("limit_price", "")
        amount      = round(qty * limit_price, 2) if qty and limit_price else ""
        order_id    = order.get("id", "")

        row = {
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":      symbol,
            "action":      exec_result.get("action", ""),
            "qty":         qty,
            "limit_price": limit_price,
            "amount":      amount,
            "order_id":    order_id,
            "signal":      analysis.get("signal", ""),
            "pred_return": f"{analysis.get('pred_return', 0.0)*100:+.3f}%" if "pred_return" in analysis else "",
            "dir_acc":     f"{metrics.get('oos_dir_acc', 0.0)*100:.1f}%" if metrics.get("oos_dir_acc") is not None else "",
            "kelly_used":  "Kelly" in reason,
        }

        fieldnames = list(row.keys())
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
            header_color = "#00cc88"
            header       = f"[{symbol}]  COMPRA enviada ✓"
        elif action == "sell":
            header_color = "#ff6655"
            header       = f"[{symbol}]  VENTA enviada ✓"
        elif action == "error":
            header_color = "#ff4455"
            header       = f"[{symbol}]  ERROR ✗"
        else:
            header_color = "#ffaa00"
            header       = f"[{symbol}]  OMITIDA"

        order_line = ""
        if order:
            order_line = (
                f"\nOrden ID : {order['id'][:12]}…"
                f"\nEstado   : {order['status']}"
            )

        self.order_text.setHtml(
            f'<span style="color:{header_color}; font-weight:bold;">{header}</span>'
            f'<br><span style="color:#a0c0a0;">{reason}{order_line.replace(chr(10), "<br>")}</span>'
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
        """Refresca el portfolio automáticamente al activar esa pestaña."""
        if self.tab_main.widget(index) is self.portfolio_widget:
            if self.executor:
                self.portfolio_widget.set_executor(self.executor)
            self.portfolio_widget.refresh()

    def _on_chart_timeframe_requested(self, symbol: str, timeframe: str) -> None:
        """Carga datos diarios o intraday 1H según la petición del gráfico."""
        if timeframe == "Diario":
            result = self._results.get(symbol)
            if result:
                self.chart.update_chart(result["df"], symbol)
        elif timeframe == "1H":
            if not self.bot:
                return
            self._set_status(f"[{symbol}] Cargando datos intraday 1H…")
            try:
                df_intra = self.bot.loader.load_intraday(symbol, days=5)
                self.chart.update_chart(df_intra, symbol)
                self._set_status(f"[{symbol}] Gráfico 1H — últimos 5 días de mercado")
            except Exception as exc:
                self._set_status(f"[{symbol}] Error cargando 1H: {exc}", error=True)

    def _set_status(self, msg: str, error: bool = False) -> None:
        color = "#ff6677" if error else "#88aacc"
        self.status_bar.showMessage(msg)
        self.status_bar.setStyleSheet(f"color: {color};")
