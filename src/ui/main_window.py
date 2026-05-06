import traceback
import pandas as pd
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox,
    QFrame, QTextEdit, QSplitter, QStatusBar,
    QMenuBar, QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QAction

from src.config.config_manager import ConfigManager
from src.data.data_fetcher import DataFetcher
from src.analysis.indicators import IndicatorEngine
from src.analysis.ml_model import TradingModel
from src.ui.chart_widget import ChartWidget
from src.ui.config_dialog import ConfigDialog


# ────────────────────────────────────────────────────────────────────────
#  Worker — corre en hilo separado para no bloquear la UI
# ────────────────────────────────────────────────────────────────────────
class AnalysisWorker(QObject):
    finished  = pyqtSignal(dict)     # emite el resultado completo
    progress  = pyqtSignal(str)      # mensajes de estado
    error     = pyqtSignal(str)      # error legible

    def __init__(self, fetcher: DataFetcher, symbol: str, days: int):
        super().__init__()
        self.fetcher  = fetcher
        self.symbol   = symbol.upper()
        self.days     = days
        self.engine   = IndicatorEngine()
        self.model    = TradingModel()

    def run(self) -> None:
        try:
            self.progress.emit(f"Descargando barras de {self.symbol}…")
            df = self.fetcher.fetch_bars(self.symbol, self.days)

            self.progress.emit("Calculando indicadores técnicos…")
            df_ind = self.engine.compute_indicators(df)

            self.progress.emit("Escalando datos y preparando features…")
            X, y, idx = self.engine.prepare_features(df, fit_scaler=True)

            self.progress.emit("Entrenando Random Forest (puede tardar ~10 s)…")
            metrics = self.model.train(X, y)

            self.progress.emit("Generando predicción para la última barra…")
            X_latest = self.engine.get_latest_features(df)
            signal, prob_up = self.model.predict(X_latest)

            self.progress.emit("Obteniendo cotización en tiempo real…")
            quote = self.fetcher.get_quote(self.symbol)

            importance = self.model.get_feature_importance(self.engine.feature_names)

            self.finished.emit({
                "df":         df_ind,
                "symbol":     self.symbol,
                "signal":     signal,
                "prob_up":    prob_up,
                "metrics":    metrics,
                "quote":      quote,
                "importance": importance,
            })

        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ────────────────────────────────────────────────────────────────────────
#  Ventana principal
# ────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config  = config
        self.fetcher = self._build_fetcher()
        self._worker_thread: QThread | None = None

        self.setWindowTitle("AlgoTrader — Alpaca Paper Trading")
        self.setMinimumSize(1200, 760)
        self._build_menu()
        self._build_ui()
        self._set_status("Listo. Ingresa un símbolo y presiona 'Entrenar y Analizar'.")

    # ────────────── Construcción de la UI ─────────────────────────────

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        cfg_menu = menu_bar.addMenu("Configuración")
        edit_keys = QAction("Editar API Keys…", self)
        edit_keys.triggered.connect(self._open_config_dialog)
        cfg_menu.addAction(edit_keys)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        # ── Toolbar ────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        toolbar.addWidget(QLabel("Símbolo:"))
        self.symbol_input = QLineEdit("AAPL")
        self.symbol_input.setFixedWidth(90)
        self.symbol_input.setFixedHeight(32)
        self.symbol_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.symbol_input.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self.symbol_input.setStyleSheet("QLineEdit { text-transform: uppercase; }")
        toolbar.addWidget(self.symbol_input)

        toolbar.addWidget(QLabel("Días de historial:"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(14, 365)
        self.days_spin.setValue(60)
        self.days_spin.setFixedWidth(70)
        self.days_spin.setFixedHeight(32)
        toolbar.addWidget(self.days_spin)

        toolbar.addStretch()

        self.train_btn = QPushButton("▶  Entrenar y Analizar")
        self.train_btn.setFixedHeight(36)
        self.train_btn.setFixedWidth(200)
        self.train_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.train_btn.setStyleSheet(
            "QPushButton { background: #0077cc; color: white; border-radius: 5px; }"
            "QPushButton:hover { background: #0099ff; }"
            "QPushButton:disabled { background: #333355; color: #666688; }"
        )
        self.train_btn.clicked.connect(self._run_analysis)
        toolbar.addWidget(self.train_btn)

        root.addLayout(toolbar)

        # ── Splitter: gráfico | panel derecho ─────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.chart = ChartWidget()
        splitter.addWidget(self.chart)

        right_panel = self._build_right_panel()
        splitter.addWidget(right_panel)
        splitter.setSizes([820, 340])
        splitter.setStretchFactor(0, 1)

        root.addWidget(splitter, stretch=1)

        # ── Status bar ────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 0, 0, 0)

        # Signal card
        signal_frame = QFrame()
        signal_frame.setFrameShape(QFrame.Shape.StyledPanel)
        signal_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        sf_layout = QVBoxLayout(signal_frame)
        sf_layout.setSpacing(6)
        sf_layout.setContentsMargins(14, 12, 14, 12)

        self.signal_label = QLabel("—")
        self.signal_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.signal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sf_layout.addWidget(self.signal_label)

        self.prob_label = QLabel("Probabilidad de subida: —")
        self.prob_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prob_label.setFont(QFont("Segoe UI", 11))
        sf_layout.addWidget(self.prob_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a3a;")
        sf_layout.addWidget(sep)

        self.ask_label = QLabel("Ask: —")
        self.bid_label = QLabel("Bid: —")
        self.suggest_label = QLabel("Sugerencia: —")
        self.suggest_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        for lbl in (self.ask_label, self.bid_label, self.suggest_label):
            lbl.setFont(QFont("Consolas", 10))
            sf_layout.addWidget(lbl)

        layout.addWidget(signal_frame)

        # Metrics card
        metrics_frame = QFrame()
        metrics_frame.setFrameShape(QFrame.Shape.StyledPanel)
        metrics_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        mf_layout = QVBoxLayout(metrics_frame)
        mf_layout.setContentsMargins(14, 10, 14, 10)

        metrics_title = QLabel("Métricas del Modelo")
        metrics_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        metrics_title.setStyleSheet("color: #8888aa;")
        mf_layout.addWidget(metrics_title)

        self.metrics_text = QTextEdit()
        self.metrics_text.setReadOnly(True)
        self.metrics_text.setFont(QFont("Consolas", 9))
        self.metrics_text.setFixedHeight(110)
        self.metrics_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; }"
        )
        mf_layout.addWidget(self.metrics_text)
        layout.addWidget(metrics_frame)

        # Feature importance
        importance_frame = QFrame()
        importance_frame.setFrameShape(QFrame.Shape.StyledPanel)
        importance_frame.setStyleSheet(
            "QFrame { background: #12121c; border: 1px solid #2a2a3a; border-radius: 8px; }"
        )
        if_layout = QVBoxLayout(importance_frame)
        if_layout.setContentsMargins(14, 10, 14, 10)

        imp_title = QLabel("Top Features (importancia)")
        imp_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        imp_title.setStyleSheet("color: #8888aa;")
        if_layout.addWidget(imp_title)

        self.importance_text = QTextEdit()
        self.importance_text.setReadOnly(True)
        self.importance_text.setFont(QFont("Consolas", 9))
        self.importance_text.setStyleSheet(
            "QTextEdit { background: #0d0d14; border: none; color: #a0a0c0; }"
        )
        if_layout.addWidget(self.importance_text)
        layout.addWidget(importance_frame, stretch=1)

        return panel

    # ────────────── Lógica ────────────────────────────────────────────

    def _build_fetcher(self) -> DataFetcher | None:
        if self.config.has_valid_config():
            api_key, secret_key = self.config.get_credentials()
            return DataFetcher(api_key, secret_key)
        return None

    def _run_analysis(self) -> None:
        if not self.fetcher:
            self._open_config_dialog()
            return

        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            self._set_status("Error: ingresa un símbolo válido.", error=True)
            return

        days = self.days_spin.value()
        self.train_btn.setEnabled(False)
        self.chart.clear()
        self._reset_signal_panel()

        self._worker_thread = QThread()
        self._worker = AnalysisWorker(self.fetcher, symbol, days)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._set_status)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)

        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(lambda: self.train_btn.setEnabled(True))

        self._worker_thread.start()

    def _on_analysis_done(self, result: dict) -> None:
        df       = result["df"]
        signal   = result["signal"]
        prob_up  = result["prob_up"]
        metrics  = result["metrics"]
        quote    = result["quote"]
        imp      = result["importance"]
        symbol   = result["symbol"]

        # Chart
        self.chart.update_chart(df, symbol)

        # Signal panel
        color = "#00cc88" if "COMPRAR" in signal else (
                "#ff4455" if "VENDER"  in signal else "#ffaa00")
        self.signal_label.setText(signal)
        self.signal_label.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")

        pct = prob_up * 100
        self.prob_label.setText(f"Probabilidad de subida: <b>{pct:.1f}%</b>")
        self.prob_label.setTextFormat(Qt.TextFormat.RichText)

        ask = quote["ask_price"]
        bid = quote["bid_price"]
        self.ask_label.setText(f"Ask: ${ask:.4f}  ({quote['ask_size']} acc.)")
        self.bid_label.setText(f"Bid: ${bid:.4f}  ({quote['bid_size']} acc.)")

        if "COMPRAR" in signal:
            suggested = bid + 0.01
            self.suggest_label.setText(f"⬆ Compra límite sugerida: ${suggested:.4f}")
        elif "VENDER" in signal:
            suggested = ask - 0.01
            self.suggest_label.setText(f"⬇ Venta límite sugerida:  ${suggested:.4f}")
        else:
            self.suggest_label.setText("↔ Sin oferta clara — esperar señal")

        # Metrics
        m = metrics
        self.metrics_text.setPlainText(
            f"CV Accuracy : {m['cv_accuracy_mean']*100:.1f}% ± {m['cv_accuracy_std']*100:.1f}%\n"
            f"Train Acc.  : {m['train_accuracy']*100:.1f}%\n"
            f"Precisión   : {m['precision_buy']*100:.1f}%\n"
            f"Recall (BUY): {m['recall_buy']*100:.1f}%\n"
            f"Muestras    : {m['n_samples']}  (↑{m['n_buy_signals']})"
        )

        # Feature importance (top 8)
        lines = [f"{name:<16} {score*100:>5.1f}%" for name, score in list(imp.items())[:8]]
        self.importance_text.setPlainText("\n".join(lines))

        self._set_status(
            f"✓ Análisis completado — {symbol} · señal: {signal} · prob: {pct:.1f}%"
        )

    def _on_analysis_error(self, msg: str) -> None:
        self._set_status(f"Error durante el análisis.", error=True)
        self.metrics_text.setPlainText(msg)

    def _reset_signal_panel(self) -> None:
        self.signal_label.setText("…")
        self.signal_label.setStyleSheet("color: #666688;")
        self.prob_label.setText("Probabilidad de subida: —")
        self.ask_label.setText("Ask: —")
        self.bid_label.setText("Bid: —")
        self.suggest_label.setText("Sugerencia: —")
        self.metrics_text.clear()
        self.importance_text.clear()

    def _open_config_dialog(self) -> None:
        prefill = self.config.get_credentials() if self.config.has_valid_config() else ("", "")
        dlg = ConfigDialog(self, prefill=prefill)
        if dlg.exec():
            api_key, secret_key = dlg.get_credentials()
            self.config.save_config(api_key, secret_key)
            self.fetcher = self._build_fetcher()
            self._set_status("Credenciales guardadas correctamente.")

    def _set_status(self, msg: str, error: bool = False) -> None:
        color = "#ff6677" if error else "#88aacc"
        self.status_bar.showMessage(msg)
        self.status_bar.setStyleSheet(f"color: {color};")
