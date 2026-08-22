"""
ModelTrainer: ensemble XGBoost + LightGBM en modo regresión con
validación temporal (TimeSeriesSplit) y persistencia en disco.

Predice el retorno flotante del día siguiente (no clasificación binaria),
lo que permite señales proporcionales a la convicción del modelo.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import joblib
import numpy as np
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

MODEL_TYPE = "ensemble_regressor_v2"   # v2: features VIX + rendimiento relativo vs SPY

_XGB_PARAMS = dict(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    gamma=1.0,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=42,
    n_jobs=-1,
    tree_method="hist",
)

_LGB_PARAMS = dict(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_samples=20,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=42,
    n_jobs=-1,
    verbose=-1,
)


class ModelTrainer:
    """
    Ensemble XGBoost + LightGBM (regresión) entrenado con TimeSeriesSplit.
    Predice el retorno del día siguiente en cada fold, luego promedia ambos
    modelos para la inferencia final (soft voting).
    """

    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._model_xgb: XGBRegressor  | None = None
        self._model_lgb: LGBMRegressor | None = None
        self._metrics: dict = {}
        self._oos_val_indices: np.ndarray | None = None
        self._oos_val_preds:   np.ndarray | None = None

    # ── Rutas de disco ──────────────────────────────────────────────────

    def _path_xgb(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_xgb.joblib"

    def _path_lgb(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_lgb.joblib"

    def _meta_path(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_meta.joblib"

    def _scaler_path(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_scaler.joblib"

    # ── Entrenamiento ───────────────────────────────────────────────────

    @staticmethod
    def _recency_weights(n: int, half_life: int = 90) -> np.ndarray:
        """Exponential decay weights — samples near index n-1 (most recent) get weight ~1,
        samples near 0 (oldest) get weight ~0.5^(n/half_life). Sum is normalised to n."""
        i = np.arange(n, dtype=float)
        w = np.exp(np.log(0.5) / half_life * (n - 1 - i))
        w = w / w.sum() * n
        return w

    def train(self, X_raw: np.ndarray, y: np.ndarray, symbol: str, scaler=None) -> dict:
        """
        Entrena ensemble con TimeSeriesSplit(5 folds).
        y debe ser array de retornos float (no clasificación binaria).
        Los datos más recientes reciben mayor peso (exponential decay, half_life=90 días).
        """
        # Pesos globales por recencia (se indexan luego con train_idx)
        all_weights = self._recency_weights(len(y), half_life=90)

        tscv = TimeSeriesSplit(n_splits=5)
        fold_maes:     list[float] = []
        fold_ics:      list[float] = []
        fold_dir_accs: list[float] = []
        oos_pairs: list[tuple[int, float]] = []

        for train_idx, val_idx in tscv.split(X_raw):
            fold_scaler = RobustScaler()
            X_tr = fold_scaler.fit_transform(X_raw[train_idx])
            X_va = fold_scaler.transform(X_raw[val_idx])
            y_tr = y[train_idx]
            y_va = y[val_idx]
            w_tr = all_weights[train_idx]

            xgb_m = XGBRegressor(**_XGB_PARAMS)
            lgb_m = LGBMRegressor(**_LGB_PARAMS)
            xgb_m.fit(X_tr, y_tr, sample_weight=w_tr, verbose=False)
            lgb_m.fit(X_tr, y_tr, sample_weight=w_tr)

            preds = (xgb_m.predict(X_va) + lgb_m.predict(X_va)) / 2.0

            fold_maes.append(float(mean_absolute_error(y_va, preds)))
            # IC: correlación de Pearson entre predicciones y retornos reales
            if np.std(preds) > 1e-9 and np.std(y_va) > 1e-9:
                ic = float(np.corrcoef(preds, y_va)[0, 1])
            else:
                ic = 0.0
            fold_ics.append(ic)
            # Direction accuracy: ¿el signo de la predicción coincide con el real?
            dir_acc = float(np.mean(np.sign(preds) == np.sign(y_va)))
            fold_dir_accs.append(dir_acc)

            for idx, p in zip(val_idx, preds):
                oos_pairs.append((int(idx), float(p)))

        oos_pairs.sort(key=lambda x: x[0])
        self._oos_val_indices = np.array([x[0] for x in oos_pairs])
        self._oos_val_preds   = np.array([x[1] for x in oos_pairs])

        # Modelo final: escalar sobre todos los datos
        if scaler is not None:
            X_all = scaler.fit_transform(X_raw)
        else:
            X_all = X_raw

        self._model_xgb = XGBRegressor(**_XGB_PARAMS)
        self._model_lgb = LGBMRegressor(**_LGB_PARAMS)
        self._model_xgb.fit(X_all, y, sample_weight=all_weights, verbose=False)
        self._model_lgb.fit(X_all, y, sample_weight=all_weights)

        self._metrics = {
            "oos_mae":     float(np.mean(fold_maes)),
            "oos_ic":      float(np.mean(fold_ics)),
            "oos_dir_acc": float(np.mean(fold_dir_accs)),
            "n_samples":   int(len(y)),
            "n_positive":  int((y > 0).sum()),
        }

        joblib.dump(self._model_xgb, self._path_xgb(symbol))
        joblib.dump(self._model_lgb, self._path_lgb(symbol))
        joblib.dump({
            "trained_date":    date.today(),
            "n_features":      int(X_raw.shape[1]),
            "model_type":      MODEL_TYPE,
            "oos_val_indices": self._oos_val_indices,
            "oos_val_preds":   self._oos_val_preds,
            "metrics":         self._metrics,
        }, self._meta_path(symbol))

        logger.info(f"[{symbol}] Ensemble guardado — IC={np.mean(fold_ics):.3f} "
                    f"DirAcc={np.mean(fold_dir_accs)*100:.1f}%")
        return self._metrics

    # ── Caché ───────────────────────────────────────────────────────────

    def try_load_cache(self, symbol: str, n_features: int) -> bool:
        if not self._meta_path(symbol).exists():
            return False
        if not self._path_xgb(symbol).exists() or not self._path_lgb(symbol).exists():
            return False
        try:
            meta = joblib.load(self._meta_path(symbol))
            if meta.get("trained_date") != date.today():
                return False
            if meta.get("n_features") != n_features:
                return False
            if meta.get("model_type") != MODEL_TYPE:
                return False
            self._model_xgb       = joblib.load(self._path_xgb(symbol))
            self._model_lgb       = joblib.load(self._path_lgb(symbol))
            self._metrics         = meta["metrics"]
            self._oos_val_indices = meta.get("oos_val_indices")
            self._oos_val_preds   = meta.get("oos_val_preds")
            logger.info(f"[{symbol}] Caché válido — ensemble cargado sin reentrenar.")
            return True
        except Exception:
            return False

    def save_scaler(self, symbol: str, scaler) -> None:
        joblib.dump(scaler, self._scaler_path(symbol))

    def load_scaler(self, symbol: str):
        path = self._scaler_path(symbol)
        return joblib.load(path) if path.exists() else None

    def has_model(self, symbol: str) -> bool:
        return self._path_xgb(symbol).exists() and self._path_lgb(symbol).exists()

    # ── Predicción ──────────────────────────────────────────────────────

    def predict(self, X: np.ndarray, threshold: float = 0.005) -> tuple[str, float]:
        """
        Devuelve (signal, pred_return) donde pred_return es el retorno esperado.
        threshold: retorno mínimo esperado para señal COMPRAR (default 0.5%).
        """
        if self._model_xgb is None or self._model_lgb is None:
            raise RuntimeError("Modelos no entrenados. Llama a train() o try_load_cache() primero.")

        pred_xgb    = float(self._model_xgb.predict(X)[0])
        pred_lgb    = float(self._model_lgb.predict(X)[0])
        pred_return = (pred_xgb + pred_lgb) / 2.0

        weak_thr = threshold * 0.4   # umbral para señal débil

        if pred_return >= threshold:
            signal = "COMPRAR"
        elif pred_return >= weak_thr:
            signal = "COMPRAR (débil)"
        elif pred_return <= -threshold:
            signal = "VENDER"
        elif pred_return <= -weak_thr:
            signal = "VENDER (débil)"
        else:
            signal = "NEUTRAL"

        return signal, pred_return

    def get_feature_importance(self, feature_names: list[str]) -> dict:
        if self._model_xgb is None:
            return {}
        imp_xgb = self._model_xgb.feature_importances_
        imp_lgb = self._model_lgb.feature_importances_ if self._model_lgb else imp_xgb
        avg_imp = (imp_xgb + imp_lgb) / 2.0
        return dict(sorted(
            zip(feature_names, avg_imp),
            key=lambda x: x[1],
            reverse=True,
        ))

    @property
    def last_metrics(self) -> dict:
        return self._metrics

    @property
    def oos_val_indices(self) -> np.ndarray | None:
        return self._oos_val_indices

    @property
    def oos_val_preds(self) -> np.ndarray | None:
        return self._oos_val_preds
