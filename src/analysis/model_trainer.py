"""
ModelTrainer: regresión con validación temporal (TimeSeriesSplit) y persistencia.

Soporta 7 tipos de modelo controlados desde settings.json:
  xgb_lgb_ensemble   — Ensemble XGBoost + LightGBM (por defecto)
  xgboost            — XGBoost solo
  lightgbm           — LightGBM solo
  random_forest      — Random Forest (sklearn)
  ridge              — Ridge Regression (sklearn)
  gradient_boosting  — Gradient Boosting (sklearn)
  xgb_rf_ensemble    — Ensemble XGBoost + Random Forest
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import joblib
import numpy as np
from lightgbm import LGBMRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

# ── Parámetros por defecto ───────────────────────────────────────────────────

_XGB_PARAMS = dict(
    n_estimators=500, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
    gamma=1.0, reg_alpha=0.1, reg_lambda=1.0,
    random_state=42, n_jobs=-1, tree_method="hist",
)

_LGB_PARAMS = dict(
    n_estimators=500, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, min_child_samples=20,
    reg_alpha=0.1, reg_lambda=1.0,
    random_state=42, n_jobs=-1, verbose=-1,
)

_RF_PARAMS = dict(
    n_estimators=300, max_depth=10, min_samples_leaf=5,
    n_jobs=-1, random_state=42,
)

_GB_PARAMS = dict(
    n_estimators=300, max_depth=5, learning_rate=0.05,
    subsample=0.8, random_state=42,
)

# Versión de los datos de entrada. Si cambia la forma de obtener/ajustar los
# precios, se sube y los modelos cacheados con la versión anterior se descartan.
#   1 → Alpaca con adjustment="raw" (precios sin ajustar por splits, bug)
#   2 → todas las fuentes ajustadas por splits y dividendos
DATA_VERSION = 2

# ── Configuración por tipo ───────────────────────────────────────────────────

# Mapea model_type → (kind_a, kind_b); kind_b = None si es modelo simple
_MODEL_CONFIGS: dict[str, tuple[str, str | None]] = {
    "xgb_lgb_ensemble":  ("xgboost",         "lightgbm"),
    "xgboost":           ("xgboost",          None),
    "lightgbm":          ("lightgbm",         None),
    "random_forest":     ("random_forest",    None),
    "ridge":             ("ridge",            None),
    "gradient_boosting": ("gradient_boosting",None),
    "xgb_rf_ensemble":   ("xgboost",         "random_forest"),
}


def _build_model(kind: str):
    if kind == "xgboost":
        return XGBRegressor(**_XGB_PARAMS)
    if kind == "lightgbm":
        return LGBMRegressor(**_LGB_PARAMS)
    if kind == "random_forest":
        return RandomForestRegressor(**_RF_PARAMS)
    if kind == "ridge":
        return Ridge(alpha=1.0)
    if kind == "gradient_boosting":
        return GradientBoostingRegressor(**_GB_PARAMS)
    raise ValueError(f"Modelo desconocido: {kind!r}")


def _fit(model, X: np.ndarray, y: np.ndarray, weights: np.ndarray):
    """Llama a fit con sample_weight si el modelo lo acepta."""
    kind = type(model).__name__
    if kind in ("XGBRegressor",):
        model.fit(X, y, sample_weight=weights, verbose=False)
    elif kind in ("LGBMRegressor", "RandomForestRegressor",
                  "GradientBoostingRegressor", "Ridge"):
        model.fit(X, y, sample_weight=weights)
    else:
        model.fit(X, y)
    return model


def _predict(model, X: np.ndarray) -> np.ndarray:
    return model.predict(X)


def _importance(model, n_features: int) -> np.ndarray:
    if hasattr(model, "feature_importances_"):
        return model.feature_importances_
    # Ridge: usa |coef_| como proxy
    if hasattr(model, "coef_"):
        return np.abs(model.coef_)
    return np.ones(n_features) / n_features


# ── Clase principal ──────────────────────────────────────────────────────────

class ModelTrainer:
    """
    Entrenador de regresión configurable.
    model_type controla qué algoritmo(s) se usan; si es None se lee de settings.json.
    """

    def __init__(self, model_dir: Path, model_type: str | None = None):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        if model_type is None:
            try:
                from src.config.settings_manager import settings
                model_type = settings.get("model_type") or "xgb_lgb_ensemble"
            except Exception:
                model_type = "xgb_lgb_ensemble"

        if model_type not in _MODEL_CONFIGS:
            logger.warning(f"model_type desconocido '{model_type}', usando xgb_lgb_ensemble.")
            model_type = "xgb_lgb_ensemble"

        self.model_type = model_type
        self._kind_a, self._kind_b = _MODEL_CONFIGS[model_type]

        self._model_a = None
        self._model_b = None
        self._metrics: dict = {}
        self._oos_val_indices: np.ndarray | None = None
        self._oos_val_preds:   np.ndarray | None = None

    # ── Rutas de disco (incluyen model_type para coexistencia) ──────────────

    def _path_a(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_{self.model_type}_a.joblib"

    def _path_b(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_{self.model_type}_b.joblib"

    def _meta_path(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_{self.model_type}_meta.joblib"

    def _scaler_path(self, symbol: str) -> Path:
        return self.model_dir / f"{symbol.upper()}_{self.model_type}_scaler.joblib"

    # ── Entrenamiento ────────────────────────────────────────────────────────

    @staticmethod
    def _recency_weights(n: int, half_life: int = 90) -> np.ndarray:
        i = np.arange(n, dtype=float)
        w = np.exp(np.log(0.5) / half_life * (n - 1 - i))
        return w / w.sum() * n

    def train(self, X_raw: np.ndarray, y: np.ndarray, symbol: str, scaler=None) -> dict:
        """
        Entrena con TimeSeriesSplit(5 folds).
        y debe ser array de retornos float.
        Los datos más recientes reciben mayor peso (exponential decay, half_life=90).
        """
        all_weights = self._recency_weights(len(y))
        tscv = TimeSeriesSplit(n_splits=5)

        fold_maes:     list[float] = []
        fold_ics:      list[float] = []
        fold_dir_accs: list[float] = []
        oos_pairs: list[tuple[int, float]] = []

        for train_idx, val_idx in tscv.split(X_raw):
            fold_scaler = RobustScaler()
            X_tr = fold_scaler.fit_transform(X_raw[train_idx])
            X_va = fold_scaler.transform(X_raw[val_idx])
            y_tr, y_va = y[train_idx], y[val_idx]
            w_tr = all_weights[train_idx]

            ma = _fit(_build_model(self._kind_a), X_tr, y_tr, w_tr)
            preds = _predict(ma, X_va)

            if self._kind_b:
                mb = _fit(_build_model(self._kind_b), X_tr, y_tr, w_tr)
                preds = (preds + _predict(mb, X_va)) / 2.0

            fold_maes.append(float(mean_absolute_error(y_va, preds)))
            ic = (float(np.corrcoef(preds, y_va)[0, 1])
                  if np.std(preds) > 1e-9 and np.std(y_va) > 1e-9 else 0.0)
            fold_ics.append(ic)
            fold_dir_accs.append(float(np.mean(np.sign(preds) == np.sign(y_va))))

            for idx, p in zip(val_idx, preds):
                oos_pairs.append((int(idx), float(p)))

        oos_pairs.sort(key=lambda x: x[0])
        self._oos_val_indices = np.array([x[0] for x in oos_pairs])
        self._oos_val_preds   = np.array([x[1] for x in oos_pairs])

        # Modelo final con todos los datos
        X_all = scaler.fit_transform(X_raw) if scaler is not None else X_raw

        self._model_a = _fit(_build_model(self._kind_a), X_all, y, all_weights)
        joblib.dump(self._model_a, self._path_a(symbol))

        if self._kind_b:
            self._model_b = _fit(_build_model(self._kind_b), X_all, y, all_weights)
            joblib.dump(self._model_b, self._path_b(symbol))

        self._metrics = {
            "oos_mae":     float(np.mean(fold_maes)),
            "oos_ic":      float(np.mean(fold_ics)),
            "oos_dir_acc": float(np.mean(fold_dir_accs)),
            "n_samples":   int(len(y)),
            "n_positive":  int((y > 0).sum()),
        }

        joblib.dump({
            "trained_date":    date.today(),
            "n_features":      int(X_raw.shape[1]),
            "model_type":      self.model_type,
            "data_version":    DATA_VERSION,
            "oos_val_indices": self._oos_val_indices,
            "oos_val_preds":   self._oos_val_preds,
            "metrics":         self._metrics,
        }, self._meta_path(symbol))

        logger.info(
            f"[{symbol}] {self.model_type} guardado — "
            f"IC={np.mean(fold_ics):.3f} DirAcc={np.mean(fold_dir_accs)*100:.1f}%"
        )
        return self._metrics

    # ── Caché ────────────────────────────────────────────────────────────────

    def try_load_cache(self, symbol: str, n_features: int) -> bool:
        if not self._meta_path(symbol).exists():
            return False
        if not self._path_a(symbol).exists():
            return False
        if self._kind_b and not self._path_b(symbol).exists():
            return False
        try:
            meta = joblib.load(self._meta_path(symbol))
            if meta.get("trained_date") != date.today():
                return False
            if meta.get("n_features") != n_features:
                return False
            if meta.get("model_type") != self.model_type:
                return False
            if meta.get("data_version") != DATA_VERSION:
                return False
            self._model_a        = joblib.load(self._path_a(symbol))
            self._model_b         = joblib.load(self._path_b(symbol)) if self._kind_b else None
            self._metrics         = meta["metrics"]
            self._oos_val_indices = meta.get("oos_val_indices")
            self._oos_val_preds   = meta.get("oos_val_preds")
            logger.info(f"[{symbol}] Caché válido — {self.model_type} cargado sin reentrenar.")
            return True
        except Exception:
            return False

    def save_scaler(self, symbol: str, scaler) -> None:
        joblib.dump(scaler, self._scaler_path(symbol))

    def load_scaler(self, symbol: str):
        path = self._scaler_path(symbol)
        return joblib.load(path) if path.exists() else None

    def has_model(self, symbol: str) -> bool:
        return self._path_a(symbol).exists()

    # ── Predicción ───────────────────────────────────────────────────────────

    def predict(self, X: np.ndarray, threshold: float = 0.005) -> tuple[str, float]:
        if self._model_a is None:
            raise RuntimeError("Modelo no entrenado. Llama a train() o try_load_cache() primero.")

        pred = float(_predict(self._model_a, X)[0])
        if self._model_b is not None:
            pred = (pred + float(_predict(self._model_b, X)[0])) / 2.0

        weak_thr = threshold * 0.4

        if pred >= threshold:
            signal = "COMPRAR"
        elif pred >= weak_thr:
            signal = "COMPRAR (débil)"
        elif pred <= -threshold:
            signal = "VENDER"
        elif pred <= -weak_thr:
            signal = "VENDER (débil)"
        else:
            signal = "NEUTRAL"

        return signal, pred

    def get_feature_importance(self, feature_names: list[str]) -> dict:
        if self._model_a is None:
            return {}
        n = len(feature_names)
        imp = _importance(self._model_a, n)
        if self._model_b is not None:
            imp = (imp + _importance(self._model_b, n)) / 2.0
        return dict(sorted(zip(feature_names, imp), key=lambda x: x[1], reverse=True))

    @property
    def last_metrics(self) -> dict:
        return self._metrics

    @property
    def oos_val_indices(self) -> np.ndarray | None:
        return self._oos_val_indices

    @property
    def oos_val_preds(self) -> np.ndarray | None:
        return self._oos_val_preds
