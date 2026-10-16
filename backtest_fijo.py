"""
Backtest de referencia CONGELADO — la única vara de medir del proyecto
(ver DECISIONS.md, "Fase 2 paso 3").

    .\\.venv\\Scripts\\python.exe backtest_fijo.py snapshot      # una sola vez: congela los datos
    .\\.venv\\Scripts\\python.exe backtest_fijo.py run           # walk-forward, periodo de desarrollo
    .\\.venv\\Scripts\\python.exe backtest_fijo.py holdout       # UNA vez por variante, último año
    .\\.venv\\Scripts\\python.exe backtest_fijo.py run --strategy momentum   # otros enfoques (STRATEGIES)

  Universo ampliado (S&P 500, snapshot v2 con fundamentales SEC y resultados trimestrales):
    .\\.venv\\Scripts\\python.exe backtest_fijo.py snapshot --snapshot v2
    .\\.venv\\Scripts\\python.exe backtest_fijo.py run --snapshot v2 --strategy h1_quality_value
    .\\.venv\\Scripts\\python.exe backtest_fijo.py snapshot-form4        # H3: compras de directivos

Reglas que garantizan que dos ejecuciones son comparables:
  - Datos: snapshot en backtest_data/v1/ (Yahoo ajustado + VIX/SPY + calendario),
    nunca se vuelve a descargar. El manifest guarda el hash de cada fichero.
  - Mismas fechas, mismo universo, mismos costes, random_state=42 en los modelos.
  - Walk-forward anual con ventana expansiva: para predecir el año Y solo se
    entrena con filas anteriores al 1 de enero de Y (menos 1 día de purga, porque
    el target de la última fila usa el cierre del día siguiente).
  - Ejecución: señal en t (con cierre de t) → compra open[t+1], venta open[t+2],
    0.05% de coste por lado. Cartera equiponderada entre señales, máx. 10% por valor.
  - Holdout (2025-10-01 → 2026-10-13): no se calcula con `run`. `holdout` se niega a
    ejecutarse dos veces para la misma configuración.

Cada ejecución añade una fila a backtest_results/historial.csv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import pickle
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis.feature_engineer import FEATURE_COLS, FeatureEngineer
from src.analysis.model_trainer import _MODEL_CONFIGS, DATA_VERSION, ModelTrainer, _build_model, _fit
from src.data.sp100 import SP100_SYMBOLS

logger = logging.getLogger("backtest_fijo")

# ── Configuración congelada ──────────────────────────────────────────────────

SNAPSHOTS      = {"v1": ROOT / "backtest_data" / "v1",          # S&P 100 (98 valores)
                  "v2": ROOT / "backtest_data" / "v2_sp500"}    # S&P 500 + SEC + resultados
FORM4_DIR      = ROOT / "backtest_data" / "form4_v1"   # H3: Form 4 de directivos del universo v2
FORM4_UNTIL    = "2026q3"                              # último trimestre publicado al congelar
SNAPSHOT_DIR   = SNAPSHOTS["v1"]       # se cambia con --snapshot
RESULTS_DIR    = ROOT / "backtest_results"
DATA_START     = "2010-01-01"
DATA_END       = "2026-10-14"          # exclusivo → última barra 2026-10-13
DEV_START      = "2016-01-01"          # primer día con predicción fuera de muestra
HOLDOUT_START  = "2025-10-01"          # todo lo posterior está reservado
BUY_THRESHOLD  = 0.005                 # igual que producción (COMPRAR fuerte)
COST_PCT       = 0.0005                # por lado
MAX_WEIGHT     = 0.10                  # máx. 10% del capital por valor
PURGE_DAYS     = 1


# ── Snapshot de datos ────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def cmd_snapshot(args) -> None:
    if args.snapshot == "v2":
        return cmd_snapshot_v2(args)
    from dotenv import load_dotenv
    from src.data.data_loader import DataLoader

    if (SNAPSHOT_DIR / "manifest.json").exists() and not args.overwrite:
        sys.exit(f"El snapshot ya existe en {SNAPSHOT_DIR}. Está congelado: no se sobrescribe.")

    load_dotenv(ROOT / ".env")
    (SNAPSHOT_DIR / "prices").mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / "calendar").mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:   # sin la caché de 20h de producción
        dl = DataLoader(os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", ""), Path(tmp))
        market = dl.load_market(start=DATA_START)
        for name, df in market.items():
            df[df.index < pd.Timestamp(DATA_END, tz="UTC")].to_parquet(SNAPSHOT_DIR / f"market_{name}.parquet")

        failed = []
        for i, sym in enumerate(SP100_SYMBOLS, 1):
            try:
                df = dl.load_yfinance(sym, start=DATA_START, end=DATA_END)
                df.to_parquet(SNAPSHOT_DIR / "prices" / f"{sym}.parquet")
                with open(SNAPSHOT_DIR / "calendar" / f"{sym}.pkl", "wb") as f:
                    pickle.dump(dl.load_calendar(sym), f)
                print(f"[{i:3d}/{len(SP100_SYMBOLS)}] {sym}: {len(df)} barras {df.index[0].date()} → {df.index[-1].date()}")
            except Exception as exc:
                failed.append(sym)
                print(f"[{i:3d}/{len(SP100_SYMBOLS)}] {sym}: ERROR {exc}")
            time.sleep(0.3)

    files = sorted(p for p in SNAPSHOT_DIR.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "created":   datetime.now().isoformat(timespec="seconds"),
        "source":    "Yahoo Finance auto_adjust=True (precios), yfinance (calendario), ^VIX/SPY",
        "data_start": DATA_START, "data_end_exclusive": DATA_END,
        "failed":    failed,
        "files":     {str(p.relative_to(SNAPSHOT_DIR)).replace("\\", "/"): _sha(p) for p in files},
    }
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nSnapshot congelado: {len(files)} ficheros. Fallidos: {failed or 'ninguno'}")


def cmd_snapshot_v2(args) -> None:
    """S&P 500 actual: precios ajustados (Yahoo), cierre ajustado solo por splits + splits
    (para la capitalización de H1), fundamentales SEC y resultados trimestrales (H2)."""
    import yfinance as yf
    from src.data.earnings import fetch_yahoo
    from src.data.fundamentals import FACTS_URL, _get, slim_facts
    from src.data.sp500 import SP500, yahoo_ticker

    if (SNAPSHOT_DIR / "manifest.json").exists() and not args.overwrite:
        sys.exit(f"El snapshot ya existe en {SNAPSHOT_DIR}. Está congelado: no se sobrescribe.")
    # Mientras no hay manifest, la descarga es reanudable: los precios y resultados ya
    # guardados se reutilizan y la SEC se vuelve a pedir siempre (sin manifest no hay congelación).
    for sub in ("prices", "close_split", "splits", "sec", "earnings"):
        (SNAPSHOT_DIR / sub).mkdir(parents=True, exist_ok=True)

    end = pd.Timestamp(DATA_END, tz="UTC")
    for name, tk in (("vix", "^VIX"), ("spy", "SPY")):
        df = yf.Ticker(tk).history(start=DATA_START, end=DATA_END, auto_adjust=True)
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index, utc=True)
        df[["open", "high", "low", "close", "volume"]].to_parquet(SNAPSHOT_DIR / f"market_{name}.parquet")

    failed: dict[str, str] = {}
    syms = list(SP500)
    for i, sym in enumerate(syms, 1):
        try:
            have = all((SNAPSHOT_DIR / sub / f"{sym}.parquet").exists()
                       for sub in ("prices", "close_split", "splits", "earnings"))
            if have:
                slim = slim_facts(_get(FACTS_URL.format(cik=SP500[sym][1])).json(), SP500[sym][1])
                (SNAPSHOT_DIR / "sec" / f"{sym}.json").write_text(json.dumps(slim), encoding="utf-8")
                print(f"[{i:3d}/{len(syms)}] {sym}: reanudado (solo SEC, {len(slim['facts'])} etiquetas)", flush=True)
                continue
            t = yf.Ticker(yahoo_ticker(sym))
            raw = t.history(start=DATA_START, end=DATA_END, auto_adjust=False)
            adj = t.history(start=DATA_START, end=DATA_END, auto_adjust=True)
            if adj.empty or raw.empty:
                raise ValueError("Yahoo sin datos")
            for df in (raw, adj):
                df.columns = [c.lower() for c in df.columns]
                df.index = pd.to_datetime(df.index, utc=True)
            adj[["open", "high", "low", "close", "volume"]].dropna().to_parquet(SNAPSHOT_DIR / "prices" / f"{sym}.parquet")
            raw[["close"]].dropna().to_parquet(SNAPSHOT_DIR / "close_split" / f"{sym}.parquet")
            sp = t.splits
            sp = sp[sp > 0] if sp is not None else pd.Series(dtype=float)
            sp.index = pd.to_datetime(sp.index, utc=True).tz_localize(None).normalize()
            sp.rename("ratio").to_frame().to_parquet(SNAPSHOT_DIR / "splits" / f"{sym}.parquet")

            slim = slim_facts(_get(FACTS_URL.format(cik=SP500[sym][1])).json(), SP500[sym][1])
            (SNAPSHOT_DIR / "sec" / f"{sym}.json").write_text(json.dumps(slim), encoding="utf-8")

            earn = fetch_yahoo(sym)
            earn = earn[earn["available"] < end]
            earn.to_parquet(SNAPSHOT_DIR / "earnings" / f"{sym}.parquet")
            print(f"[{i:3d}/{len(syms)}] {sym}: {len(adj)} barras, {len(slim['facts'])} etiquetas SEC, "
                  f"{len(earn)} resultados", flush=True)
        except Exception as exc:
            failed[sym] = str(exc)[:120]
            for sub, ext in (("prices", "parquet"), ("close_split", "parquet"), ("splits", "parquet"),
                             ("sec", "json"), ("earnings", "parquet")):
                (SNAPSHOT_DIR / sub / f"{sym}.{ext}").unlink(missing_ok=True)
            print(f"[{i:3d}/{len(syms)}] {sym}: ERROR {exc}", flush=True)
        time.sleep(0.3)

    files = sorted(p for p in SNAPSHOT_DIR.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "created":   datetime.now().isoformat(timespec="seconds"),
        "universe":  "S&P 500 actual (src/data/sp500.py) — con sesgo de supervivencia",
        "source":    "Yahoo (precios auto_adjust, cierre solo-splits, splits, resultados) + SEC companyfacts",
        "data_start": DATA_START, "data_end_exclusive": DATA_END,
        "failed":    failed,
        "files":     {str(p.relative_to(SNAPSHOT_DIR)).replace("\\", "/"): _sha(p) for p in files},
    }
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nSnapshot v2 congelado: {len(files)} ficheros. Fallidos: {len(failed)} {list(failed)[:20]}")


def cmd_snapshot_form4(args) -> None:
    """H3: operaciones P/S de directivos (Form 4) de los emisores del S&P 500, 2006T1 → FORM4_UNTIL."""
    from src.data.insiders import download_quarters
    from src.data.sp500 import SP500
    if (FORM4_DIR / "manifest.json").exists() and not args.overwrite:
        sys.exit(f"El snapshot ya existe en {FORM4_DIR}. Está congelado: no se sobrescribe.")
    FORM4_DIR.mkdir(parents=True, exist_ok=True)
    ciks = {int(v[1]) for v in SP500.values()}
    trades = download_quarters(ciks, ROOT / "data_cache" / "form345", until=FORM4_UNTIL)
    trades = trades[trades["filed"] < pd.Timestamp(DATA_END)].reset_index(drop=True)
    trades.to_parquet(FORM4_DIR / "trades.parquet")
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "source":  "SEC Insider Transactions Data Sets 2006q1 → " + FORM4_UNTIL,
        "rows":    len(trades),
        "files":   {"trades.parquet": _sha(FORM4_DIR / "trades.parquet")},
    }
    (FORM4_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nSnapshot Form 4 congelado: {len(trades)} operaciones "
          f"({(trades['code'] == 'P').sum()} compras).")


def _load_form4() -> tuple[pd.DataFrame, str]:
    mpath = FORM4_DIR / "manifest.json"
    if not mpath.exists():
        sys.exit("No hay snapshot de Form 4. Ejecuta primero: backtest_fijo.py snapshot-form4")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    for rel, h in manifest["files"].items():
        if _sha(FORM4_DIR / rel) != h:
            sys.exit(f"El snapshot de Form 4 ha cambiado ({rel}). Los resultados ya no serían comparables.")
    return pd.read_parquet(FORM4_DIR / "trades.parquet"), manifest["files"]["trades.parquet"]


def _load_snapshot() -> tuple[dict, dict[str, pd.DataFrame], dict[str, dict], str]:
    mpath = SNAPSHOT_DIR / "manifest.json"
    if not mpath.exists():
        sys.exit("No hay snapshot. Ejecuta primero: backtest_fijo.py snapshot")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    for rel, h in manifest["files"].items():
        if _sha(SNAPSHOT_DIR / rel) != h:
            sys.exit(f"El snapshot ha cambiado ({rel}). Los resultados ya no serían comparables.")
    market = {n: pd.read_parquet(SNAPSHOT_DIR / f"market_{n}.parquet") for n in ("vix", "spy")}
    prices, calendars = {}, {}
    for p in sorted((SNAPSHOT_DIR / "prices").glob("*.parquet")):
        prices[p.stem] = pd.read_parquet(p)
        cal = SNAPSHOT_DIR / "calendar" / f"{p.stem}.pkl"
        if cal.exists():                                   # v2 no tiene calendario
            with open(cal, "rb") as f:
                calendars[p.stem] = pickle.load(f)
    snap_hash = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()[:12]
    return market, prices, calendars, snap_hash


# ── Walk-forward por símbolo ─────────────────────────────────────────────────

def _blocks(holdout: bool) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Bloques [inicio, fin) de predicción. Desarrollo: años naturales; holdout: un bloque."""
    tz = "UTC"
    if holdout:
        return [(pd.Timestamp(HOLDOUT_START, tz=tz), pd.Timestamp(DATA_END, tz=tz))]
    out, start = [], pd.Timestamp(DEV_START, tz=tz)
    end_dev = pd.Timestamp(HOLDOUT_START, tz=tz)
    while start < end_dev:
        nxt = min(pd.Timestamp(year=start.year + 1, month=1, day=1, tz=tz), end_dev)
        out.append((start, nxt))
        start = nxt
    return out


def predict_symbol(sym, df, calendar, market, model_type, holdout, future_n: int = 1) -> pd.DataFrame:
    kind_a, kind_b = _MODEL_CONFIGS[model_type]
    fe = FeatureEngineer()
    X, y, idx, _ = fe.prepare_raw(df, future_n=future_n, calendar=calendar, market=market)
    purge = max(PURGE_DAYS, future_n)       # el target de las últimas filas usa precios del bloque de test
    rows = []
    for start, end in _blocks(holdout):
        test = (idx >= start) & (idx < end)
        n_train = int((idx < start).sum()) - purge
        if not test.any() or n_train < 500:
            continue
        X_tr, y_tr = X[:n_train], y[:n_train]
        scaler = RobustScaler().fit(X_tr)
        w = ModelTrainer._recency_weights(n_train)
        m = _fit(_build_model(kind_a), scaler.transform(X_tr), y_tr, w)
        pred = m.predict(scaler.transform(X[test]))
        if kind_b:
            mb = _fit(_build_model(kind_b), scaler.transform(X_tr), y_tr, w)
            pred = (pred + mb.predict(scaler.transform(X[test]))) / 2.0
        rows.append(pd.DataFrame({"date": idx[test], "symbol": sym, "pred": pred, "target_cc": y[test]}))
    return pd.concat(rows) if rows else pd.DataFrame(columns=["date", "symbol", "pred", "target_cc"])


def _open_to_open(prices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Retorno bruto ejecutable de una señal en t: open[t+2]/open[t+1]-1, indexado por t."""
    cols = {}
    for sym, df in prices.items():
        o = df["open"]
        cols[sym] = o.shift(-2) / o.shift(-1) - 1
    return pd.DataFrame(cols)


# ── Simulación de cartera y estadísticas ─────────────────────────────────────

def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def _perf(daily: pd.Series) -> dict:
    daily = daily.fillna(0.0)
    eq = (1 + daily).cumprod()
    years = max(len(daily) / 252, 1e-9)
    return {
        "total_return": float(eq.iloc[-1] - 1),
        "cagr":         float(eq.iloc[-1] ** (1 / years) - 1),
        "sharpe":       float(daily.mean() / (daily.std() + 1e-12) * math.sqrt(252)),
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
    }


def evaluate(preds: pd.DataFrame, oo: pd.DataFrame, signal_filter=None) -> dict:
    preds = preds.copy()
    preds["ret_oo"] = [oo.at[d, s] if d in oo.index else np.nan for d, s in zip(preds["date"], preds["symbol"])]
    preds = preds.dropna(subset=["ret_oo"])

    preds["buy"] = preds["pred"] >= BUY_THRESHOLD
    if signal_filter is not None:
        preds["buy"] &= signal_filter(preds)
    net = lambda r: ((1 + r) * (1 - COST_PCT) - (1 + COST_PCT)) / (1 + COST_PCT)
    preds["ret_net"] = net(preds["ret_oo"])

    dates = pd.DatetimeIndex(sorted(preds["date"].unique()))
    by_date = preds.groupby("date")

    strat, bench, ics = [], [], []
    for d in dates:
        g = by_date.get_group(d)
        b = g[g["buy"]]
        w = min(1.0 / len(b), MAX_WEIGHT) if len(b) else 0.0
        strat.append(float((b["ret_net"] * w).sum()))
        bench.append(float(g["ret_oo"].mean()))
        if len(g) >= 10 and g["pred"].std() > 0:
            ics.append(spearmanr(g["pred"], g["ret_oo"]).statistic)

    strat = pd.Series(strat, index=dates)
    bench = pd.Series(bench, index=dates)
    ics = np.array([x for x in ics if not np.isnan(x)])
    trades = preds[preds["buy"]]
    wins = int((trades["ret_net"] > 0).sum())
    lo, hi = _wilson(wins, len(trades))
    ic_t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics)))) if len(ics) > 2 else 0.0
    dir_acc = float((np.sign(preds["pred"]) == np.sign(preds["target_cc"])).mean())

    s_perf, b_perf = _perf(strat), _perf(bench)
    crit = {
        "1_sharpe_gt_benchmark":   s_perf["sharpe"] > b_perf["sharpe"],
        "2_ic_positive_t_gt_2":    bool(ics.mean() > 0 and ic_t > 2),
        "3_hit_rate_ci_low_gt_50": lo > 0.5,
    }
    by_year = (
        pd.DataFrame({"s": strat, "b": bench})
        .groupby(strat.index.year)
        .apply(lambda x: pd.Series({"estrategia": (1 + x["s"]).prod() - 1, "benchmark": (1 + x["b"]).prod() - 1}))
    )
    return {
        "periodo":          f"{dates[0].date()} → {dates[-1].date()}",
        "n_dias":           len(dates),
        "n_simbolos":       int(preds["symbol"].nunique()),
        "n_predicciones":   len(preds),
        "estrategia":       s_perf,
        "benchmark_equiponderado": b_perf,
        "n_operaciones":    len(trades),
        "exposicion_media": float((preds.groupby("date")["buy"].sum().clip(upper=1 / MAX_WEIGHT) * MAX_WEIGHT).clip(upper=1).mean()),
        "acierto_compras":  wins / len(trades) if len(trades) else 0.0,
        "acierto_compras_ic95": [lo, hi],
        "ret_neto_medio_operacion": float(trades["ret_net"].mean()) if len(trades) else 0.0,
        "ic_medio":         float(ics.mean()) if len(ics) else 0.0,
        "ic_t_stat":        ic_t,
        "dir_acc_cc":       dir_acc,
        "criterios":        crit,
        "ACEPTADO":         all(crit.values()),
        "por_anio":         {int(k): {kk: float(vv) for kk, vv in v.items()} for k, v in by_year.iterrows()},
    }


# ── Variantes (Fase 3: filtros sobre señales, nunca features nuevas) ─────────

def _variant_filter(name: str, calendars: dict[str, dict]):
    if name == "base":
        return None
    if name.startswith("earnings_skip_"):
        n_days = int(name.rsplit("_", 1)[1])
        events = {}
        for s, cal in calendars.items():
            e = cal.get("earnings")
            events[s] = np.sort(pd.DatetimeIndex(e).normalize().values.astype("datetime64[D]")) if e is not None and len(e) else None

        def f(df: pd.DataFrame) -> pd.Series:
            keep = np.ones(len(df), dtype=bool)
            d = df["date"].dt.tz_convert(None).dt.normalize().values.astype("datetime64[D]")
            for i, (s, di) in enumerate(zip(df["symbol"].values, d)):
                ev = events.get(s)
                if ev is None:
                    continue
                j = np.searchsorted(ev, di, side="right")          # siguiente evento estrictamente posterior
                if j < len(ev) and (ev[j] - di).astype(int) <= n_days:
                    keep[i] = False                               # la posición (t+1→t+2) cruzaría resultados
            return pd.Series(keep, index=df.index)
        return f
    sys.exit(f"Variante desconocida: {name}")


# ── Enfoques por ranking con posiciones de H días (pre-registro E1–E3) ───────

TOP_N = 10

STRATEGIES = {
    #  nombre       H (días)  descripción
    "daily_ml":  (1,  "modelo de producción, señal diaria pred >= 0.5% (referencia)"),
    "momentum":  (21, "E1 momentum 12-1: retorno t-252 -> t-21, top 10"),
    "reversal":  (5,  "E2 reversión: los 10 que más caen en 5 días"),
    "ml20":      (20, "E3 random_forest con target a 20 días, top 10"),
    # Pre-registro 2026-10-15 (DECISIONS.md). Solo con --snapshot v2.
    "h1_quality_value":     (21, "H1 calidad+valor: rango(beneficio bruto/activos) + rango(patrimonio/capitalización), top 40"),
    "h2_earnings_surprise": (21, "H2 sorpresa en resultados: % sorpresa del último anuncio (<=63 sesiones), top 40"),
    # Pre-registro 2026-10-16. Solo con --snapshot v2 + snapshot-form4.
    "h3_insider_buying":    (21, "H3 compras oportunistas de directivos (Form 4, últimas 21 sesiones), máx. 40"),
}
TOP_N_BY_STRATEGY = {"h1_quality_value": 40, "h2_earnings_surprise": 40, "h3_insider_buying": 40}
V2_ONLY = {"h1_quality_value", "h2_earnings_surprise", "h3_insider_buying"}
# H3: solo se compran valores con señal (> 0); con menos de este mínimo, el periodo va al benchmark
SIGNAL_ONLY = {"h3_insider_buying": 5}


def _panel(prices: dict[str, pd.DataFrame], col: str) -> pd.DataFrame:
    return pd.DataFrame({s: df[col] for s, df in prices.items()}).sort_index()


def _scores(strategy, prices, model_type, market, calendars, holdout, snap_hash) -> pd.DataFrame:
    close = _panel(prices, "close")
    if strategy == "momentum":
        return close.shift(21) / close.shift(252) - 1
    if strategy == "reversal":
        return -(close / close.shift(5) - 1)
    if strategy == "ml20":
        preds = _predictions(model_type, market, prices, calendars, holdout, snap_hash, future_n=20)
        return preds.pivot(index="date", columns="symbol", values="pred").reindex(close.index)
    if strategy == "h1_quality_value":
        return _scores_h1(close)
    if strategy == "h2_earnings_surprise":
        return _scores_h2(close)
    if strategy == "h3_insider_buying":
        return _scores_h3(close)
    sys.exit(f"Estrategia desconocida: {strategy}")


def _scores_h1(close: pd.DataFrame) -> pd.DataFrame:
    """H1: rango percentil de GP/A + rango percentil de B/M entre los elegibles del día.
    Elegibles: sector no financiero ni inmobiliario, sin costes de siniestros de seguros,
    GP/A y B/M conocidos, patrimonio > 0."""
    from src.data.fundamentals import is_insurer, quality_value_inputs
    from src.data.sp500 import EXCLUDED_SECTORS_H1, SP500
    gpa, bm = {}, {}
    for sym in close.columns:
        if SP500.get(sym, ("",))[0] in EXCLUDED_SECTORS_H1:
            continue
        fpath = SNAPSHOT_DIR / "sec" / f"{sym}.json"
        if not fpath.exists():
            continue
        facts = json.loads(fpath.read_text(encoding="utf-8"))
        if is_insurer(facts):
            continue
        cs = pd.read_parquet(SNAPSHOT_DIR / "close_split" / f"{sym}.parquet")["close"]
        sp = pd.read_parquet(SNAPSHOT_DIR / "splits" / f"{sym}.parquet")["ratio"]
        qv = quality_value_inputs(facts, cs, sp)
        gpa[sym], bm[sym] = qv["gpa"], qv["bm"]
    gpa = pd.DataFrame(gpa).reindex(close.index)
    bm = pd.DataFrame(bm).reindex(close.index)
    bm = bm.where(bm > 0)
    ok = gpa.notna() & bm.notna()
    gpa, bm = gpa.where(ok), bm.where(ok)
    return (gpa.rank(axis=1, pct=True) + bm.rank(axis=1, pct=True)).reindex(columns=close.columns)


def _scores_h2(close: pd.DataFrame) -> pd.DataFrame:
    """H2: % de sorpresa del último resultado público (válido 63 sesiones)."""
    from src.data.earnings import surprise_score
    out = {}
    for sym in close.columns:
        epath = SNAPSHOT_DIR / "earnings" / f"{sym}.parquet"
        if epath.exists():
            out[sym] = surprise_score(pd.read_parquet(epath), close.index)
    return pd.DataFrame(out).reindex(index=close.index, columns=close.columns)


def _scores_h3(close: pd.DataFrame) -> pd.DataFrame:
    """H3: nº de directivos con compra oportunista conocida en las últimas 21 sesiones
    (+ importe / 1e12 como desempate). 0 si no hay compras."""
    from src.data.insiders import insider_score, opportunistic_purchases
    from src.data.sp500 import SP500
    trades, _ = _load_form4()
    buys = opportunistic_purchases(trades)
    out = {}
    for sym in close.columns:
        cik = int(SP500[sym][1])
        out[sym] = insider_score(buys[buys["issuer_cik"] == cik], close.index)
    return pd.DataFrame(out).reindex(index=close.index, columns=close.columns)


def evaluate_ranked(scores: pd.DataFrame, prices: dict[str, pd.DataFrame], hold: int, holdout: bool,
                    top_n: int = TOP_N, signal_min: int | None = None) -> dict:
    """
    Cada `hold` días: con la puntuación de t (cierre de t) se compran los TOP_N mejores
    a open[t+1] y se mantienen hasta open[t+1+hold]. Cartera equiponderada; coste
    COST_PCT por lado sobre la rotación real.
    Con `signal_min` (H3): solo se compran valores con puntuación > 0 (máx. top_n,
    equiponderados); si hay menos de signal_min, ese periodo va al benchmark equiponderado
    y no cuenta para el acierto. El coste se calcula sobre la rotación de pesos.
    """
    opens = _panel(prices, "open")
    scores = scores.reindex(opens.index)
    r = opens.shift(-1) / opens - 1                    # r[k]: open[k] -> open[k+1]
    dates = opens.index
    start = pd.Timestamp(HOLDOUT_START if holdout else DEV_START, tz="UTC")
    end = pd.Timestamp(DATA_END if holdout else HOLDOUT_START, tz="UTC")

    # La posición entera (hasta open[t+1+hold]) debe caer dentro del periodo.
    first = int(np.searchsorted(dates, start)) - 1    # señal la víspera del primer día
    i, reb = max(first, 0), []
    while i + 1 + hold < len(dates) and dates[i + 1 + hold] < end:
        reb.append(i)
        i += hold

    strat = pd.Series(np.nan, index=dates)
    held_prev: set[str] = set()
    last_day = None
    ics, pos_rets, n_pos = [], [], 0
    w_prev: dict[str, float] = {}
    n_signal = 0
    for i in reb:
        sc = scores.iloc[i]
        valid = sc.notna() & opens.iloc[i + 1].notna() & opens.iloc[i + 1 + hold].notna()
        sc = sc[valid]
        if len(sc) < top_n * 2:
            continue
        fwd = opens.iloc[i + 1 + hold][sc.index] / opens.iloc[i + 1][sc.index] - 1
        ics.append(spearmanr(sc, fwd).statistic)
        if signal_min is not None:
            sig = sc[sc > 0].nlargest(top_n)
            on = len(sig) >= signal_min
            n_signal += on
            held = set(sig.index) if on else set(sc.index)
            w = {s_: 1 / len(held) for s_ in held}
            turn = sum(abs(w.get(k, 0) - w_prev.get(k, 0)) for k in set(w) | set(w_prev))
            days = list(range(i + 1, i + 1 + hold))
            strat.iloc[days] = r.iloc[days][sorted(held)].mean(axis=1).to_numpy()
            strat.iloc[i + 1] -= turn * COST_PCT
            if on:
                for s_ in held:
                    pos_rets.append((1 + fwd[s_]) * (1 - COST_PCT) / (1 + COST_PCT) - 1)
                n_pos += len(held)
            w_prev, held_prev, last_day = w, held, i + hold
            continue
        held = set(sc.nlargest(top_n).index)
        bought = len(held - held_prev) / top_n
        sold = len(held_prev - held) / top_n
        days = list(range(i + 1, i + 1 + hold))
        strat.iloc[days] = r.iloc[days][sorted(held)].mean(axis=1).to_numpy()
        strat.iloc[i + 1] -= (bought + sold) * COST_PCT
        for s_ in held:                                   # resultado por posición (ida y vuelta)
            pos_rets.append((1 + fwd[s_]) * (1 - COST_PCT) / (1 + COST_PCT) - 1)
        n_pos += len(held)
        held_prev, last_day = held, i + hold
    if last_day is not None:                              # cierre de la última cartera
        strat.iloc[last_day] -= (1.0 if signal_min is not None else len(held_prev) / top_n) * COST_PCT

    strat = strat.dropna()
    bench = r.loc[strat.index].mean(axis=1)
    ics = np.array([x for x in ics if not np.isnan(x)])
    pos_rets = np.array(pos_rets)
    wins = int((pos_rets > 0).sum())
    lo, hi = _wilson(wins, len(pos_rets))
    ic_t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics)))) if len(ics) > 2 else 0.0

    s_perf, b_perf = _perf(strat), _perf(bench)
    crit = {
        "1_sharpe_gt_benchmark":   s_perf["sharpe"] > b_perf["sharpe"],
        "2_ic_positive_t_gt_2":    bool(len(ics) and ics.mean() > 0 and ic_t > 2),
        "3_hit_rate_ci_low_gt_50": lo > 0.5,
    }
    by_year = (
        pd.DataFrame({"s": strat, "b": bench}).groupby(strat.index.year)
        .apply(lambda x: pd.Series({"estrategia": (1 + x["s"]).prod() - 1, "benchmark": (1 + x["b"]).prod() - 1}))
    )
    return {
        "periodo":          f"{strat.index[0].date()} → {strat.index[-1].date()}",
        "n_dias":           len(strat),
        "n_simbolos":       int(opens.shape[1]),
        "n_rebalanceos":    len(ics),
        "estrategia":       s_perf,
        "benchmark_equiponderado": b_perf,
        "n_operaciones":    n_pos,
        "acierto_compras":  wins / len(pos_rets) if len(pos_rets) else 0.0,
        "acierto_compras_ic95": [lo, hi],
        "ret_neto_medio_operacion": float(pos_rets.mean()) if len(pos_rets) else 0.0,
        "ic_medio":         float(ics.mean()) if len(ics) else 0.0,
        "ic_t_stat":        ic_t,
        "criterios":        crit,
        "ACEPTADO":         all(crit.values()),
        **({"rebalanceos_con_senal": n_signal} if signal_min is not None else {}),
        "por_anio":         {int(k): {kk: float(vv) for kk, vv in v.items()} for k, v in by_year.iterrows()},
    }


# ── Ejecución ────────────────────────────────────────────────────────────────

def _config(model_type: str, variant: str, snap_hash: str, strategy: str = "daily_ml") -> dict:
    cfg = {
        "model_type": model_type, "variant": variant, "snapshot": snap_hash,
        "data_version": DATA_VERSION, "features": len(FEATURE_COLS),
        "dev_start": DEV_START, "holdout_start": HOLDOUT_START,
        "buy_threshold": BUY_THRESHOLD, "cost_pct": COST_PCT, "max_weight": MAX_WEIGHT,
    }
    if strategy != "daily_ml":       # sin la clave, la referencia diaria conserva su config_hash
        cfg.update(strategy=strategy, hold=STRATEGIES[strategy][0],
                   top_n=TOP_N_BY_STRATEGY.get(strategy, TOP_N))
    if strategy in SIGNAL_ONLY:
        cfg.update(signal_min=SIGNAL_ONLY[strategy], form4=_load_form4()[1])
    return cfg


def _predictions(model_type, market, prices, calendars, holdout, snap_hash, future_n: int = 1) -> pd.DataFrame:
    """Las predicciones solo dependen del modelo y los datos (no de la variante): se cachean."""
    tag = "holdout" if holdout else "dev"
    horizon = "" if future_n == 1 else f"_h{future_n}"
    cache = RESULTS_DIR / f"preds_{tag}_{model_type}{horizon}_{snap_hash}_dv{DATA_VERSION}.parquet"
    if cache.exists():
        print(f"Usando predicciones cacheadas: {cache.name}")
        return pd.read_parquet(cache)
    parts, t0 = [], time.time()
    for i, (sym, df) in enumerate(prices.items(), 1):
        parts.append(predict_symbol(sym, df, calendars[sym], market, model_type, holdout, future_n))
        print(f"[{i:3d}/{len(prices)}] {sym} ({time.time() - t0:.0f}s)", flush=True)
    preds = pd.concat(parts, ignore_index=True)
    preds.to_parquet(cache)
    return preds


def cmd_run(args, holdout: bool = False) -> None:
    from src.config.settings_manager import settings
    model_type = args.model or settings.get("model_type") or "xgb_lgb_ensemble"
    if args.strategy in V2_ONLY and args.snapshot != "v2":
        sys.exit(f"{args.strategy} solo se mide sobre el universo ampliado: añade --snapshot v2")
    RESULTS_DIR.mkdir(exist_ok=True)
    market, prices, calendars, snap_hash = _load_snapshot()
    cfg = _config(model_type, args.variant, snap_hash, args.strategy)
    cfg_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]

    if holdout:
        log = RESULTS_DIR / "holdout_ejecutados.json"
        done = json.loads(log.read_text(encoding="utf-8")) if log.exists() else {}
        if cfg_hash in done:
            sys.exit(f"El holdout ya se ejecutó para esta configuración el {done[cfg_hash]['fecha']}. "
                     "No se repite (regla del criterio pre-registrado).")

    if args.strategy == "daily_ml":
        preds = _predictions(model_type, market, prices, calendars, holdout, snap_hash)
        res = evaluate(preds, _open_to_open(prices), _variant_filter(args.variant, calendars))
    else:
        if args.variant != "base":
            sys.exit("Las variantes (filtros) solo existen para la estrategia daily_ml.")
        scores = _scores(args.strategy, prices, model_type, market, calendars, holdout, snap_hash)
        res = evaluate_ranked(scores, prices, STRATEGIES[args.strategy][0], holdout,
                              TOP_N_BY_STRATEGY.get(args.strategy, TOP_N), SIGNAL_ONLY.get(args.strategy))
    res["config"], res["config_hash"] = cfg, cfg_hash
    res["tipo"] = "HOLDOUT" if holdout else "desarrollo"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = args.variant if args.strategy == "daily_ml" else args.strategy
    if args.snapshot != "v1":
        label += f"_{args.snapshot}"
    out = RESULTS_DIR / f"{stamp}_{res['tipo']}_{model_type}_{label}.json"
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    hist = RESULTS_DIR / "historial.csv"
    row = pd.DataFrame([{
        "fecha": stamp, "tipo": res["tipo"], "model": model_type, "variant": label,
        "config_hash": cfg_hash, "sharpe": res["estrategia"]["sharpe"],
        "sharpe_bench": res["benchmark_equiponderado"]["sharpe"], "cagr": res["estrategia"]["cagr"],
        "cagr_bench": res["benchmark_equiponderado"]["cagr"], "max_dd": res["estrategia"]["max_drawdown"],
        "n_ops": res["n_operaciones"], "acierto": res["acierto_compras"], "ic": res["ic_medio"],
        "ic_t": res["ic_t_stat"], "aceptado": res["ACEPTADO"],
    }])
    row.to_csv(hist, mode="a", header=not hist.exists(), index=False)

    if holdout:
        done[cfg_hash] = {"fecha": stamp, "config": cfg, "resultado": out.name}
        log.write_text(json.dumps(done, indent=2), encoding="utf-8")

    print(json.dumps({k: res[k] for k in res if k not in ("por_anio", "config")}, indent=2, ensure_ascii=False, default=str))
    print(f"\nResultado guardado en {out}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--overwrite", action="store_true")
    f4 = sub.add_parser("snapshot-form4"); f4.add_argument("--overwrite", action="store_true")
    s.add_argument("--snapshot", choices=list(SNAPSHOTS), default="v1")
    for name in ("run", "holdout"):
        p = sub.add_parser(name)
        p.add_argument("--snapshot", choices=list(SNAPSHOTS), default="v1")
        p.add_argument("--model", choices=sorted(_MODEL_CONFIGS), default=None)
        p.add_argument("--variant", default="base")
        p.add_argument("--strategy", choices=list(STRATEGIES), default="daily_ml")
    args = ap.parse_args()
    global SNAPSHOT_DIR
    SNAPSHOT_DIR = SNAPSHOTS[getattr(args, "snapshot", "v2")]
    if args.cmd == "snapshot-form4":
        cmd_snapshot_form4(args)
    elif args.cmd == "snapshot":
        cmd_snapshot(args)
    else:
        cmd_run(args, holdout=(args.cmd == "holdout"))


if __name__ == "__main__":
    main()
