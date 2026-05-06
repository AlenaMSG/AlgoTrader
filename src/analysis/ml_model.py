import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report


class TradingModel:
    def __init__(self):
        self.model = RandomForestClassifier(
            n_estimators=300,
            max_depth=12,
            min_samples_split=5,
            min_samples_leaf=3,
            max_features="sqrt",
            random_state=42,
            n_jobs=-1,
            class_weight="balanced",  # compensa clases desbalanceadas
        )
        self._trained = False
        self._feature_importances: dict = {}
        self.last_metrics: dict = {}

    def train(self, X: np.ndarray, y: np.ndarray) -> dict:
        # TimeSeriesSplit respeta el orden temporal — nunca mezclar pasado/futuro
        tscv = TimeSeriesSplit(n_splits=5)
        cv_scores = []
        for train_idx, val_idx in tscv.split(X):
            self.model.fit(X[train_idx], y[train_idx])
            preds = self.model.predict(X[val_idx])
            cv_scores.append(accuracy_score(y[val_idx], preds))

        # Entrenamiento final sobre todo el conjunto
        self.model.fit(X, y)
        self._trained = True

        # Reporte sobre el conjunto completo (aproximado — solo para UI)
        y_pred = self.model.predict(X)
        report = classification_report(y, y_pred, output_dict=True, zero_division=0)

        self.last_metrics = {
            "cv_accuracy_mean": float(np.mean(cv_scores)),
            "cv_accuracy_std":  float(np.std(cv_scores)),
            "train_accuracy":   float(accuracy_score(y, y_pred)),
            "precision_buy":    float(report.get("1", {}).get("precision", 0)),
            "recall_buy":       float(report.get("1", {}).get("recall", 0)),
            "n_samples":        len(y),
            "n_buy_signals":    int(y.sum()),
        }
        return self.last_metrics

    def predict(self, X_latest: np.ndarray) -> tuple[str, float]:
        if not self._trained:
            raise RuntimeError("El modelo no ha sido entrenado todavía.")

        proba = self.model.predict_proba(X_latest)[0]
        # proba[1] = probabilidad de que el precio suba en las próximas 4h
        prob_up = float(proba[1])

        if prob_up >= 0.65:
            signal = "COMPRAR"
        elif prob_up >= 0.55:
            signal = "COMPRAR (débil)"
        elif prob_up <= 0.35:
            signal = "VENDER"
        elif prob_up <= 0.45:
            signal = "VENDER (débil)"
        else:
            signal = "NEUTRAL"

        return signal, prob_up

    def get_feature_importance(self, feature_names: list[str]) -> dict:
        if not self._trained:
            return {}
        importances = self.model.feature_importances_
        return dict(sorted(
            zip(feature_names, importances),
            key=lambda x: x[1],
            reverse=True,
        ))

    @property
    def is_trained(self) -> bool:
        return self._trained
