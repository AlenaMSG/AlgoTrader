"""
FeatureEngineer: indicadores técnicos + features de calendario para XGBoost.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.preprocessing import RobustScaler

FUTURE_N = 1  # predecir el día siguiente

FEATURE_COLS: list[str] = [
    # Retornos logarítmicos
    "log_ret_1d", "log_ret_5d", "log_ret_20d",
    # Tendencia
    "sma20", "sma50", "sma_ratio", "price_sma20",
    # MACD
    "macd", "macd_signal", "macd_hist",
    # Momentum
    "rsi",
    # Bandas de Bollinger
    "bb_upper", "bb_lower", "bb_mid", "bb_bwidth", "bb_pct",
    # Volatilidad
    "atr",
    # Volumen
    "vol_sma20", "vol_ratio",
    # OHLC
    "hl_range", "close",
    # Calendario corporativo (earnings + dividendos)
    "days_to_earnings", "is_earnings_week", "days_to_exdiv", "is_pre_exdiv",
    # Contexto de mercado (VIX + momentum relativo vs SPY)
    "vix", "vix_chg_5d", "rel_ret_5d", "rel_ret_20d",
]


class FeatureEngineer:
    """
    Transforma barras OHLCV en features escalados listos para XGBoost.
    RobustScaler es más resistente a outliers de precio que StandardScaler.
    """

    def __init__(self):
        self.scaler  = RobustScaler()
        self._fitted = False

    @property
    def feature_names(self) -> list[str]:
        return FEATURE_COLS

    # ------------------------------------------------------------------ #
    #  Cálculo de indicadores                                              #
    # ------------------------------------------------------------------ #

    def compute(self, df: pd.DataFrame, calendar: dict | None = None,
                market: dict | None = None) -> pd.DataFrame:
        out = df.copy()

        # Retornos logarítmicos
        out["log_ret_1d"]  = np.log(out["close"] / out["close"].shift(1))
        out["log_ret_5d"]  = np.log(out["close"] / out["close"].shift(5))
        out["log_ret_20d"] = np.log(out["close"] / out["close"].shift(20))

        # Medias móviles
        out["sma20"]       = ta.sma(out["close"], length=20)
        out["sma50"]       = ta.sma(out["close"], length=50)
        out["sma_ratio"]   = out["sma20"] / out["sma50"].replace(0, np.nan)
        out["price_sma20"] = out["close"] / out["sma20"].replace(0, np.nan)

        # MACD (12, 26, 9)
        macd_df = ta.macd(out["close"], fast=12, slow=26, signal=9)
        cols = macd_df.columns.tolist()
        out["macd"]        = macd_df[cols[0]]
        out["macd_hist"]   = macd_df[cols[1]]
        out["macd_signal"] = macd_df[cols[2]]

        # RSI(14)
        out["rsi"] = ta.rsi(out["close"], length=14)

        # Bandas de Bollinger (20, 2σ)
        bb   = ta.bbands(out["close"], length=20, std=2.0)
        _col = lambda p: next(c for c in bb.columns if c.startswith(p))
        out["bb_upper"]  = bb[_col("BBU_")]
        out["bb_lower"]  = bb[_col("BBL_")]
        out["bb_mid"]    = bb[_col("BBM_")]
        out["bb_bwidth"] = bb[_col("BBB_")]
        out["bb_pct"]    = bb[_col("BBP_")]

        # ATR(14)
        out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=14)

        # Volumen relativo
        out["vol_sma20"] = ta.sma(out["volume"], length=20)
        out["vol_ratio"] = out["volume"] / out["vol_sma20"].replace(0, np.nan)

        # Rango intrabar normalizado
        out["hl_range"] = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)

        # ── Features de calendario ─────────────────────────────────────────
        cal = calendar or {}
        out["days_to_earnings"] = self._days_to_next(
            out.index, cal.get("earnings"), default=90
        ).values
        out["is_earnings_week"] = (out["days_to_earnings"] <= 5).astype(float)
        out["days_to_exdiv"]    = self._days_to_next(
            out.index, cal.get("dividends"), default=90
        ).values
        out["is_pre_exdiv"]     = (out["days_to_exdiv"] <= 5).astype(float)

        # ── Contexto de mercado (VIX + momentum relativo vs SPY) ──────────
        mkt = market or {}
        vix_df = mkt.get("vix")
        spy_df = mkt.get("spy")

        if vix_df is not None and not vix_df.empty:
            v = vix_df["close"].reindex(out.index, method="ffill")
            out["vix"]       = v
            out["vix_chg_5d"] = v.pct_change(5)
        else:
            out["vix"]        = 20.0
            out["vix_chg_5d"] = 0.0

        if spy_df is not None and not spy_df.empty:
            s = spy_df["close"].reindex(out.index, method="ffill")
            out["rel_ret_5d"]  = out["log_ret_5d"]  - np.log(s / s.shift(5))
            out["rel_ret_20d"] = out["log_ret_20d"] - np.log(s / s.shift(20))
        else:
            out["rel_ret_5d"]  = 0.0
            out["rel_ret_20d"] = 0.0

        return out

    # ------------------------------------------------------------------ #
    #  Preparación para entrenamiento                                      #
    # ------------------------------------------------------------------ #

    def prepare_raw(
        self,
        df: pd.DataFrame,
        future_n: int = FUTURE_N,
        calendar: dict | None = None,
        market: dict | None = None,
    ) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex, np.ndarray]:
        """
        Devuelve (X sin escalar, y_ret, índice temporal, close prices).

        y_ret: retorno flotante del día siguiente (regresión, no clasificación).
          El modelo aprende a predecir el retorno real, no solo la dirección.
        calendar: dict con "earnings" y "dividends" (DatetimeIndex).
        """
        data = self.compute(df, calendar=calendar, market=market)

        ret            = data["close"].shift(-future_n) / data["close"] - 1
        data["target"] = ret.astype(np.float32)

        data.dropna(subset=FEATURE_COLS + ["target"], inplace=True)
        data = data.iloc[:-future_n]

        X_raw  = data[FEATURE_COLS].values.astype(np.float32)
        y      = data["target"].values.astype(np.float32)
        idx    = data.index
        closes = data["close"].values.astype(np.float64)

        return X_raw, y, idx, closes

    def get_latest_x(self, df: pd.DataFrame, calendar: dict | None = None,
                      market: dict | None = None) -> np.ndarray:
        """Features de la última barra disponible para inferencia."""
        if not self._fitted:
            raise RuntimeError("El scaler aún no está ajustado. Llama a ModelTrainer.train() primero.")
        data = self.compute(df, calendar=calendar, market=market)
        data.dropna(subset=FEATURE_COLS, inplace=True)
        raw = data[FEATURE_COLS].iloc[[-1]].values.astype(np.float32)
        return self.scaler.transform(raw)

    # ------------------------------------------------------------------ #
    #  Utilidades                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _days_to_next(
        date_index:  pd.DatetimeIndex,
        event_dates,
        default:     int = 90,
    ) -> pd.Series:
        """Vectorizado: para cada fecha, días hasta el próximo evento (capped en `default`)."""
        if event_dates is None or len(event_dates) == 0:
            return pd.Series(float(default), index=date_index)

        dates_d  = date_index.normalize().values.astype("datetime64[D]")
        events_d = np.sort(
            pd.DatetimeIndex(event_dates).normalize().values.astype("datetime64[D]")
        )

        next_idx = np.searchsorted(events_d, dates_d, side="right")
        result   = np.full(len(dates_d), float(default))
        valid    = next_idx < len(events_d)
        if valid.any():
            diff = (events_d[next_idx[valid]] - dates_d[valid])
            result[valid] = np.minimum(
                diff.astype("timedelta64[D]").astype(float),
                float(default),
            )

        return pd.Series(result, index=date_index)
