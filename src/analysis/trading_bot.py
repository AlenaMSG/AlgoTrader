"""
TradingBot: orquesta DataLoader + FeatureEngineer + ModelTrainer
para el pipeline completo de análisis por símbolo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.data.data_loader import DataLoader
from src.analysis.feature_engineer import FeatureEngineer
from src.analysis.model_trainer import ModelTrainer
from src.analysis.backtester import Backtester


class TradingBot:
    def __init__(self, data_loader: DataLoader, model_dir: Path, model_type: str | None = None):
        self.loader     = data_loader
        self.model_dir  = Path(model_dir)
        self.model_type = model_type   # None → ModelTrainer lee de settings.json
        self._market: dict | None = None  # cargado una vez y reutilizado

    def _get_market(self, start_date: str) -> dict:
        if self._market is None:
            self._market = self.loader.load_market(start=start_date)
        return self._market

    def run_symbol(
        self,
        symbol:           str,
        start_date:       str   = "2010-01-01",
        return_threshold: float = 0.005,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        """
        Pipeline completo para un símbolo:
          1. Descarga historial con yfinance (con caché)
          2. Fetch calendario (earnings + dividendos)
          3. Fetch sentimiento de noticias (VADER, últimos 3 días)
          4. Fetch put/call ratio de opciones
          5. Calcula indicadores técnicos + features de calendario
          6. Entrena ensemble XGBoost+LightGBM con TimeSeriesSplit (regresión)
          7. Genera la señal sobre la última barra
          8. Obtiene cotización ask/bid en tiempo real (Alpaca)
          9. Backtest OOS con las predicciones del CV

        return_threshold: retorno mínimo predicho para señal COMPRAR.
          0.005 → comprar solo si el modelo predice ≥ 0.5% de retorno (default)
          0.010 → solo si predice ≥ 1.0% (más selectivo)
        """
        emit = progress or (lambda _: None)

        emit(f"[{symbol}] Descargando historial desde {start_date} (Yahoo Finance)…")
        df_raw = self.loader.load(symbol, start=start_date)

        emit(f"[{symbol}] Obteniendo datos de calendario (earnings, dividendos)…")
        calendar = self.loader.load_calendar(symbol)

        emit(f"[{symbol}] Obteniendo sentimiento de noticias y put/call ratio…")
        news_data    = self.loader.load_news(symbol)
        options_data = self.loader.load_options(symbol)

        emit(f"[{symbol}] Obteniendo datos de mercado (VIX, SPY)…")
        market = self._get_market(start_date)

        emit(f"[{symbol}] Calculando indicadores técnicos y features de calendario…")
        fe = FeatureEngineer()
        X_raw, y, idx, closes = fe.prepare_raw(df_raw, calendar=calendar, market=market)

        trainer    = ModelTrainer(self.model_dir, model_type=self.model_type)
        n_features = X_raw.shape[1]

        if trainer.try_load_cache(symbol, n_features):
            emit(f"[{symbol}] Modelo en caché (entrenado hoy) — omitiendo reentrenamiento…")
            saved_scaler = trainer.load_scaler(symbol)
            if saved_scaler is not None:
                fe.scaler  = saved_scaler
                fe._fitted = True
                metrics    = trainer.last_metrics
            else:
                emit(f"[{symbol}] Scaler no cacheado — reentrenando…")
                metrics = trainer.train(X_raw, y, symbol, scaler=fe.scaler)
                trainer.save_scaler(symbol, fe.scaler)
                fe._fitted = True
        else:
            emit(f"[{symbol}] Entrenando {trainer.model_type} (5 folds)…")
            metrics = trainer.train(X_raw, y, symbol, scaler=fe.scaler)
            trainer.save_scaler(symbol, fe.scaler)
            fe._fitted = True

        emit(f"[{symbol}] Generando señal sobre la última barra…")
        X_latest = fe.get_latest_x(df_raw, calendar=calendar, market=market)
        signal, pred_return = trainer.predict(X_latest, threshold=return_threshold)

        emit(f"[{symbol}] Obteniendo cotización en tiempo real (Alpaca)…")
        quote = self.loader.get_quote(symbol)

        df_feat    = fe.compute(df_raw, calendar=calendar, market=market)
        importance = trainer.get_feature_importance(fe.feature_names)

        emit(f"[{symbol}] Calculando backtest OOS…")
        backtest = None
        if trainer.oos_val_preds is not None and len(trainer.oos_val_preds) > 10:
            oos_idx    = trainer.oos_val_indices
            oos_preds  = trainer.oos_val_preds
            oos_closes = closes[oos_idx]
            oos_index  = idx[oos_idx]
            try:
                backtest = Backtester(buy_threshold=return_threshold).run(
                    oos_preds, oos_closes, oos_index, prices=df_raw
                )
            except Exception:
                backtest = None

        return {
            "df":           df_feat,
            "symbol":       symbol,
            "signal":       signal,
            "pred_return":  pred_return,
            "metrics":      metrics,
            "quote":        quote,
            "importance":   importance,
            "backtest":     backtest,
            "sentiment":    news_data,
            "options":      options_data,
        }

    def has_trained_model(self, symbol: str) -> bool:
        return ModelTrainer(self.model_dir, model_type=self.model_type).has_model(symbol)
