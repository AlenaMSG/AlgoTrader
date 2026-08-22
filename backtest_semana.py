"""
backtest_semana.py
Entrena el modelo con datos hasta el 14-Ago-2026 (como si esa fuera la fecha),
predice direccion para el 18-Ago y compara con lo que realmente pasó del 18 al 21 Ago.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import pandas as pd
import yfinance as yf

from src.config.config_manager import ConfigManager
from src.data.data_loader import DataLoader
from src.analysis.feature_engineer import FeatureEngineer
from src.analysis.model_trainer import ModelTrainer

# ── Configuración ─────────────────────────────────────────────────────
CUTOFF     = "2026-08-14"   # último día de entrenamiento (semana antes de la pasada)
REAL_DESDE = "2026-08-15"   # primer día real a comparar
REAL_HASTA = "2026-08-22"   # hasta el viernes pasado (no incluido en yfinance)
START_HIST = "2015-01-01"   # inicio del histórico de entrenamiento

# Símbolos a analizar (los más relevantes del S&P100)
SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
           "META", "TSLA", "JPM", "ORCL", "INTC",
           "AVGO", "TXN", "FCX", "TGT", "MSFT"]
SYMBOLS = list(dict.fromkeys(SYMBOLS))  # quitar duplicados

GREEN  = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
BOLD   = "\033[1m";  DIM = "\033[2m";  RESET  = "\033[0m"

def get_real_return(symbol: str) -> dict:
    """Retorno real del periodo comparado."""
    try:
        h = yf.Ticker(symbol).history(
            start=REAL_DESDE, end=REAL_HASTA, interval="1d", auto_adjust=True
        )
        if h.empty:
            return {}
        ret = (h["Close"].iloc[-1] - h["Close"].iloc[0]) / h["Close"].iloc[0]
        return {
            "retorno": ret,
            "precio_inicio": h["Close"].iloc[0],
            "precio_fin":    h["Close"].iloc[-1],
            "fecha_inicio":  h.index[0].strftime("%d/%m"),
            "fecha_fin":     h.index[-1].strftime("%d/%m"),
            "dias":          len(h),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    print(f"\n{BOLD}{'='*68}{RESET}")
    print(f"{BOLD}  BACKTEST — Como si fuera el {CUTOFF}{RESET}")
    print(f"  El modelo solo ve datos hasta el {CUTOFF}")
    print(f"  Comparamos con lo que REALMENTE paso del {REAL_DESDE} al 21-Ago")
    print(f"{BOLD}{'='*68}{RESET}\n")

    # Inicializar componentes
    cfg = ConfigManager()
    if not cfg.has_valid_config():
        print("ERROR: Credenciales Alpaca no configuradas.")
        return

    api_key, secret_key = cfg.get_credentials()
    loader = DataLoader(api_key, secret_key, cache_dir=PROJECT_ROOT / "data_cache")

    # Directorio de modelos separado para no machacar los modelos reales
    model_dir = PROJECT_ROOT / "models_backtest"
    model_dir.mkdir(exist_ok=True)

    resultados = []

    for symbol in SYMBOLS:
        print(f"  [{symbol}] Descargando y entrenando...", end=" ", flush=True)
        try:
            # 1. Descargar datos históricos completos
            df_raw = loader.load(symbol, start=START_HIST)

            # 2. Truncar en la fecha de corte (el "pasado simulado")
            df_cut = df_raw[df_raw.index.date <= pd.Timestamp(CUTOFF).date()].copy()
            if len(df_cut) < 120:
                print(f"datos insuficientes ({len(df_cut)} filas)")
                continue

            # 3. Preparar features y entrenar (sin caché para este backtest)
            fe = FeatureEngineer()
            X_raw, y, idx, closes = fe.prepare_raw(df_cut)
            trainer = ModelTrainer(model_dir)
            trainer.train(X_raw, y, symbol, scaler=fe.scaler)
            fe._fitted = True

            # 4. Predecir sobre la última barra disponible (14-Ago)
            X_latest = fe.get_latest_x(df_cut)
            signal, pred_return = trainer.predict(X_latest, threshold=0.005)
            da = trainer.last_metrics.get("oos_dir_acc", 0) * 100

            # 5. Retorno real de la semana siguiente
            real = get_real_return(symbol)
            if not real or "error" in real:
                print(f"sin datos reales")
                continue

            real_ret     = real["retorno"] * 100
            dir_pred     = "SUBE" if pred_return > 0 else "BAJA"
            dir_real     = "SUBE" if real_ret > 0 else "BAJA"
            acierto      = dir_pred == dir_real
            es_fuerte    = "débil" not in signal.lower() and signal != "NEUTRAL"

            col_sig  = GREEN if "COMPRAR" in signal else RED if "VENDER" in signal else YELLOW
            col_real = GREEN if real_ret > 0 else RED
            col_ok   = GREEN if acierto else RED
            mark     = "OK" if acierto else "FALLO"

            print(
                f"{col_sig}{signal:<20}{RESET}  "
                f"Pred: {pred_return*100:+.2f}%  "
                f"Real: {col_real}{real_ret:+.2f}%{RESET}  "
                f"DA={da:.0f}%  "
                f"{col_ok}[{mark}]{RESET}"
            )

            resultados.append({
                "symbol":   symbol,
                "signal":   signal,
                "pred_%":   pred_return * 100,
                "real_%":   real_ret,
                "da_%":     da,
                "acierto":  acierto,
                "fuerte":   es_fuerte,
            })

        except Exception as e:
            print(f"ERROR: {e}")

    if not resultados:
        print("\nNo hay resultados para mostrar.")
        return

    df = pd.DataFrame(resultados)
    total    = len(df)
    acertos  = df["acierto"].sum()
    pct      = acertos / total * 100 if total else 0

    print(f"\n{BOLD}{'='*68}{RESET}")
    print(f"{BOLD}  RESUMEN{RESET}")
    print(f"{'='*68}")
    print(f"  Simbolos analizados        : {total}")
    print(f"  Direccion acertada (total) : {acertos}/{total}  ({pct:.0f}%)")

    fuertes = df[df["fuerte"]]
    if not fuertes.empty:
        ac_f  = fuertes["acierto"].sum()
        pct_f = ac_f / len(fuertes) * 100
        col   = GREEN if pct_f >= 60 else YELLOW if pct_f >= 50 else RED
        print(f"  Solo senales FUERTES       : {ac_f}/{len(fuertes)}  ({col}{pct_f:.0f}%{RESET})")

    comprar = df[df["signal"] == "COMPRAR"]
    if not comprar.empty:
        ret_m = comprar["real_%"].mean()
        col   = GREEN if ret_m > 0 else RED
        print(f"  Retorno real medio COMPRAR : {col}{ret_m:+.2f}%{RESET}")

    vender = df[df["signal"] == "VENDER"]
    if not vender.empty:
        ret_m = vender["real_%"].mean()
        col   = GREEN if ret_m < 0 else RED
        print(f"  Retorno real medio VENDER  : {col}{ret_m:+.2f}%  (bueno si baja){RESET}")

    print(f"\n  {DIM}Periodo real comparado: {REAL_DESDE} → 21-Ago-2026{RESET}")
    print(f"  {DIM}Modelo entrenado con datos hasta: {CUTOFF}{RESET}")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    main()
