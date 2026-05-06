import numpy as np
import pandas as pd
import pandas_ta as ta
from sklearn.preprocessing import StandardScaler

RSI_LEN   = 14
SMA_SHORT = 20
SMA_LONG  = 50
BB_LEN    = 20
BB_STD    = 2.0
FUTURE_N  = 4   # horas hacia adelante para la etiqueta


class IndicatorEngine:
    def __init__(self):
        self.scaler = StandardScaler()
        self._feature_cols: list[str] = []

    # ------------------------------------------------------------------ #
    #  Cálculo de indicadores                                              #
    # ------------------------------------------------------------------ #
    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        out["RSI"] = ta.rsi(out["close"], length=RSI_LEN)
        out["SMA20"] = ta.sma(out["close"], length=SMA_SHORT)
        out["SMA50"] = ta.sma(out["close"], length=SMA_LONG)

        bb = ta.bbands(out["close"], length=BB_LEN, std=BB_STD)
        out["BB_upper"]     = bb[f"BBU_{BB_LEN}_{BB_STD}"]
        out["BB_lower"]     = bb[f"BBL_{BB_LEN}_{BB_STD}"]
        out["BB_mid"]       = bb[f"BBM_{BB_LEN}_{BB_STD}"]
        out["BB_bandwidth"] = bb[f"BBB_{BB_LEN}_{BB_STD}"]
        out["BB_pct"]       = bb[f"BBP_{BB_LEN}_{BB_STD}"]

        out["VOL_SMA20"] = ta.sma(out["volume"], length=SMA_SHORT)

        # Derived features — ratios are scale-invariant but StandardScaler
        # still normalises variance, which helps the tree splits.
        out["SMA_ratio"]    = out["SMA20"] / out["SMA50"].replace(0, np.nan)
        out["price_sma20"]  = out["close"] / out["SMA20"].replace(0, np.nan)
        out["vol_ratio"]    = out["volume"] / out["VOL_SMA20"].replace(0, np.nan)
        out["HL_range"]     = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)
        out["ret_1h"]       = out["close"].pct_change(1)
        out["ret_4h"]       = out["close"].pct_change(4)

        return out

    # ------------------------------------------------------------------ #
    #  Preparación de features + etiqueta para entrenamiento              #
    # ------------------------------------------------------------------ #
    def prepare_features(
        self, df: pd.DataFrame, fit_scaler: bool = True
    ) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
        data = self.compute_indicators(df)

        # Etiqueta: 1 si el precio cierra más alto FUTURE_N horas después
        data["target"] = (
            data["close"].shift(-FUTURE_N) > data["close"]
        ).astype(int)

        self._feature_cols = [
            "RSI", "SMA20", "SMA50",
            "BB_upper", "BB_lower", "BB_mid", "BB_bandwidth", "BB_pct",
            "volume", "VOL_SMA20",
            "SMA_ratio", "price_sma20", "vol_ratio", "HL_range",
            "ret_1h", "ret_4h",
            "open", "high", "low", "close",
        ]

        data.dropna(subset=self._feature_cols + ["target"], inplace=True)
        # Drop the last FUTURE_N rows — label is unknowable (future data)
        data = data.iloc[:-FUTURE_N]

        X_raw = data[self._feature_cols].values
        y     = data["target"].values
        idx   = data.index

        # StandardScaler: crucial para que el modelo no confunda la magnitud
        # del precio (ej. 180) con la del RSI (ej. 45) o el volumen (ej. 1e6)
        if fit_scaler:
            X = self.scaler.fit_transform(X_raw)
        else:
            X = self.scaler.transform(X_raw)

        return X, y, idx

    def get_latest_features(self, df: pd.DataFrame) -> np.ndarray:
        """Devuelve el vector de features de la última barra (para inferencia)."""
        data = self.compute_indicators(df)
        data.dropna(subset=self._feature_cols, inplace=True)
        last = data[self._feature_cols].iloc[[-1]].values
        return self.scaler.transform(last)  # mismo scaler del entrenamiento

    @property
    def feature_names(self) -> list[str]:
        return self._feature_cols
