"""
DataLoader: descarga datos históricos de Yahoo Finance y cotizaciones
en tiempo real de Alpaca Markets.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import alpaca_trade_api as tradeapi
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_SIA = SentimentIntensityAnalyzer()

logger = logging.getLogger(__name__)

PAPER_URL = "https://paper-api.alpaca.markets"


class DataLoader:
    """
    Combina Yahoo Finance (historial largo) con Alpaca (cotización actual).
    Cachea los datos en disco (Parquet) para evitar descargas repetidas.
    """

    def __init__(self, api_key: str, secret_key: str, cache_dir: Path):
        self.api = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url=PAPER_URL,
        )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Yahoo Finance                                                        #
    # ------------------------------------------------------------------ #
    def load_yfinance(
        self,
        symbol: str,
        start: str = "2010-01-01",
        end: str | None = None,
    ) -> pd.DataFrame:
        """
        Barras diarias de Yahoo Finance.
        Usa caché en disco si tiene menos de 20 horas de antigüedad.
        """
        cache_file = self.cache_dir / f"{symbol.upper()}_daily.parquet"

        if cache_file.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if age < timedelta(hours=20):
                df = pd.read_parquet(cache_file)
                logger.info(f"[{symbol}] Caché local: {len(df)} filas")
                return df

        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval="1d", auto_adjust=True)

        if df.empty:
            raise ValueError(
                f"Yahoo Finance no devolvió datos para '{symbol}'. "
                "Comprueba que el ticker sea correcto."
            )

        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df.sort_index(inplace=True)
        df.dropna(inplace=True)

        df.to_parquet(cache_file)
        logger.info(f"[{symbol}] yfinance: {len(df)} filas desde {start}")
        return df

    # ------------------------------------------------------------------ #
    #  Alpaca — cotización en tiempo real                                   #
    # ------------------------------------------------------------------ #
    def get_quote(self, symbol: str) -> dict:
        try:
            q = self.api.get_latest_quote(symbol)
            return {
                "ask_price": float(q.ap),
                "ask_size":  int(q.as_),
                "bid_price": float(q.bp),
                "bid_size":  int(q.bs),
            }
        except Exception:
            bar = self.api.get_latest_bar(symbol)
            price = float(bar.c)
            return {"ask_price": price, "ask_size": 0,
                    "bid_price": price, "bid_size": 0}

    # ------------------------------------------------------------------ #
    #  Calendario corporativo (earnings + dividendos)                      #
    # ------------------------------------------------------------------ #
    def load_calendar(self, symbol: str) -> dict:
        """
        Devuelve earnings dates y ex-dividend dates de yfinance.
        Ambos son DatetimeIndex sin timezone. Si no hay datos, devuelve None.
        """
        result = {"earnings": None, "dividends": None}
        ticker = yf.Ticker(symbol)

        try:
            ed = ticker.get_earnings_dates(limit=40)
            if ed is not None and not ed.empty:
                dates = pd.DatetimeIndex(ed.index)
                result["earnings"] = dates.tz_localize(None) if dates.tz else dates
        except Exception:
            pass

        try:
            div = ticker.dividends
            if div is not None and not div.empty:
                dates = div.index
                result["dividends"] = dates.tz_localize(None) if dates.tz else dates
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------ #
    #  Datos intraday 1H (Alpaca)                                         #
    # ------------------------------------------------------------------ #
    def load_intraday(self, symbol: str, days: int = 5) -> pd.DataFrame:
        """
        Barras de 1 hora de los últimos `days` días vía Alpaca.
        Devuelve DataFrame con columnas OHLCV en minúscula.
        """
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        try:
            bars = self.api.get_bars(
                symbol.upper(),
                "1Hour",
                start=start.isoformat(),
                end=end.isoformat(),
                adjustment="raw",
            ).df
            if bars is None or bars.empty:
                raise ValueError(f"Sin datos intraday para {symbol}")
            bars.columns = [c.lower() for c in bars.columns]
            keep = [c for c in ("open", "high", "low", "close", "volume") if c in bars.columns]
            bars = bars[keep].copy()
            bars.index = pd.to_datetime(bars.index, utc=True)
            bars.sort_index(inplace=True)
            bars.dropna(inplace=True)
            return bars
        except Exception as exc:
            raise ValueError(f"Error cargando intraday 1H para {symbol}: {exc}") from exc

    # ------------------------------------------------------------------ #
    #  Sentimiento de noticias (VADER)                                     #
    # ------------------------------------------------------------------ #
    def load_news(self, symbol: str) -> dict:
        """
        Descarga titulares recientes de yfinance y calcula sentimiento con VADER.
        Devuelve sentiment_score ([-1,1]) y sentiment_volume (nº noticias 3 días).
        """
        ticker  = yf.Ticker(symbol)
        cutoff  = datetime.now().timestamp() - 3 * 86400  # últimos 3 días
        default = {"sentiment_score": 0.0, "sentiment_volume": 0}
        try:
            raw_news = ticker.news or []
            titles: list[str] = []
            for item in raw_news:
                # yfinance puede devolver formato plano o anidado en "content"
                content = item.get("content", {}) if isinstance(item.get("content"), dict) else {}
                title   = content.get("title") or item.get("title") or ""
                ts      = (
                    item.get("providerPublishTime")
                    or item.get("published")
                    or content.get("pubDate")   # formato actual yfinance
                    or 0
                )
                if isinstance(ts, str):
                    try:
                        ts = pd.Timestamp(ts).timestamp()
                    except Exception:
                        ts = 0
                if title and float(ts) >= cutoff:
                    titles.append(title)

            if not titles:
                return default

            scores = [_SIA.polarity_scores(t)["compound"] for t in titles]
            return {
                "sentiment_score":  float(np.mean(scores)),
                "sentiment_volume": len(titles),
            }
        except Exception:
            return default

    # ------------------------------------------------------------------ #
    #  Put/call ratio (opciones)                                           #
    # ------------------------------------------------------------------ #
    def load_options(self, symbol: str) -> dict:
        """
        Calcula el put/call ratio de open interest en la cadena de opciones
        más cercana. Clamp [0.1, 10.0]. Default 1.0 si sin datos.
        """
        ticker  = yf.Ticker(symbol)
        default = {"pc_ratio": 1.0}
        try:
            expirations = ticker.options
            if not expirations:
                return default
            chain    = ticker.option_chain(expirations[0])
            puts_oi  = float(chain.puts["openInterest"].fillna(0).sum())
            calls_oi = float(chain.calls["openInterest"].fillna(0).sum())
            if calls_oi > 0:
                pc_ratio = float(np.clip(puts_oi / calls_oi, 0.1, 10.0))
            else:
                pc_ratio = 1.0
            return {"pc_ratio": pc_ratio}
        except Exception:
            return default

    # ------------------------------------------------------------------ #
    #  Datos de mercado — VIX y SPY (contexto macro)                       #
    # ------------------------------------------------------------------ #
    def load_market(self, start: str = "2010-01-01") -> dict:
        """Devuelve {"vix": df_close, "spy": df_close} con índice UTC diario."""
        return {
            "vix": self._load_market_series("^VIX", start),
            "spy": self._load_market_series("SPY",  start),
        }

    def _load_market_series(self, ticker: str, start: str) -> pd.DataFrame:
        safe_name  = ticker.replace("^", "IDX_")
        cache_file = self.cache_dir / f"{safe_name}_daily.parquet"

        if cache_file.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if age < timedelta(hours=20):
                return pd.read_parquet(cache_file)

        t  = yf.Ticker(ticker)
        df = t.history(start=start, interval="1d", auto_adjust=True)
        if df.empty:
            return pd.DataFrame(columns=["close"])

        df.columns = [c.lower() for c in df.columns]
        df = df[["close"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df.sort_index(inplace=True)
        df.dropna(inplace=True)
        df.to_parquet(cache_file)
        return df

    # ------------------------------------------------------------------ #
    #  Entrada principal                                                    #
    # ------------------------------------------------------------------ #
    def load(self, symbol: str, start: str = "2010-01-01") -> pd.DataFrame:
        """Barras diarias limpias desde `start` hasta hoy."""
        df = self.load_yfinance(symbol, start=start)
        if len(df) < 100:
            raise ValueError(
                f"Solo {len(df)} barras disponibles para '{symbol}'. "
                "Prueba con una fecha de inicio más reciente o un símbolo más líquido."
            )
        return df
