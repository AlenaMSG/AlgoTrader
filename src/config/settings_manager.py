from __future__ import annotations
import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parents[2] / "settings.json"

DEFAULTS: dict = {
    "data_source": "yahoo",
    "model_type":  "xgb_lgb_ensemble",
    "scan_mode":   "auto",
}

DATA_SOURCES = {
    "yahoo":         "Yahoo Finance (gratis, sin API key)",
    "alpaca":        "Alpaca Markets (necesita API key en .env)",
    "alpha_vantage": "Alpha Vantage (necesita API key, plan de pago recomendado)",
    "polygon":       "Polygon.io (de pago)",
}

MODEL_TYPES = {
    "xgb_lgb_ensemble": "Ensemble XGBoost + LightGBM (por defecto)",
    "xgboost":          "XGBoost solo",
    "lightgbm":         "LightGBM solo",
    "random_forest":    "Random Forest",
    "ridge":            "Ridge Regression",
    "gradient_boosting":"Gradient Boosting (sklearn)",
    "xgb_rf_ensemble":  "Ensemble XGBoost + Random Forest",
}


class SettingsManager:
    def load(self) -> dict:
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return {**DEFAULTS, **data}
        except (FileNotFoundError, json.JSONDecodeError):
            return dict(DEFAULTS)

    def save(self, settings: dict) -> None:
        merged = {**DEFAULTS, **settings}
        SETTINGS_PATH.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self, key: str):
        return self.load().get(key, DEFAULTS.get(key))


settings = SettingsManager()
