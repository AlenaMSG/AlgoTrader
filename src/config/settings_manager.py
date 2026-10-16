from __future__ import annotations
import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parents[2] / "settings.json"

DEFAULTS: dict = {
    "data_source": "yahoo",
    "model_type":  "xgb_lgb_ensemble",
    "scan_mode":   "auto",
    "strategy":    "h1_quality_value",      # estrategia principal (src/analysis/strategies.py)
}

# Fuentes de PRECIOS (velas diarias)
DATA_SOURCES = {
    "yahoo":         "gratis, sin API key, histórico desde 2010",
    "alpaca":        "API key en .env; el feed gratuito solo tiene histórico desde 27-07-2020",
    "alpha_vantage": "los precios ajustados son de pago; la clave gratuita no sirve",
    "polygon":       "de pago",
}

# Fuentes de INFORMACIÓN distinta del precio (estrategias H1–H3)
INFO_SOURCES = {
    "sec_companyfacts": {
        "nombre": "SEC EDGAR · balances (companyfacts)",
        "uso": "H1 — beneficio bruto, activos, patrimonio y acciones, con fecha de publicación",
        "coste": "Gratis, sin clave (10 peticiones/s)",
        "rol": "Principal",
    },
    "yahoo_earnings": {
        "nombre": "Yahoo · historial de resultados",
        "uso": "H2 — BPA real vs. estimado y hora del anuncio, desde ~2002",
        "coste": "Gratis, sin clave",
        "rol": "Activa",
    },
    "av_earnings": {
        "nombre": "Alpha Vantage · EARNINGS",
        "uso": "H2 — respaldo y comprobación de las sorpresas",
        "coste": "Clave gratuita: 25 peticiones/día",
        "rol": "Respaldo",
    },
    "sec_form4": {
        "nombre": "SEC EDGAR · Form 4 (directivos)",
        "uso": "H3 — compras y ventas de directivos",
        "coste": "Gratis, sin clave",
        "rol": "Pendiente",
    },
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
        merged = {**self.load(), **settings}
        SETTINGS_PATH.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self, key: str):
        return self.load().get(key, DEFAULTS.get(key))


settings = SettingsManager()
