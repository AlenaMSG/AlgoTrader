"""
DataLoader: descarga datos históricos (Yahoo Finance / Alpaca / Alpha Vantage / Polygon)
y cotizaciones en tiempo real de Alpaca Markets.

La fuente activa se lee de settings.json en cada llamada a load().
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame
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
    #  Sentimiento de noticias                                             #
    # ------------------------------------------------------------------ #
    def _load_news_av(self, symbol: str) -> dict | None:
        """
        Sentimiento de noticias vía Alpha Vantage NEWS_SENTIMENT.
        Devuelve None si la API key no está configurada o hay error.
        Más preciso que VADER porque AV ya entrega un score por artículo.
        """
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        if not api_key:
            return None
        try:
            from alpha_vantage.alphaintelligence import AlphaIntelligence
            ai = AlphaIntelligence(key=api_key, output_format="json")
            data, _ = ai.get_news_sentiment(tickers=symbol, limit=50)
            feed = data.get("feed", [])
            if not feed:
                return None
            scores = [float(item.get("overall_sentiment_score", 0.0)) for item in feed[:20]]
            return {
                "sentiment_score":  float(np.mean(scores)),
                "sentiment_volume": len(scores),
            }
        except Exception:
            return None

    def load_news(self, symbol: str) -> dict:
        """
        Sentimiento de noticias recientes.
        Usa Alpha Vantage NEWS_SENTIMENT si ALPHA_VANTAGE_API_KEY está en .env
        (score ya calculado por AV, más preciso). Si no, fallback a VADER sobre
        titulares de yfinance.
        """
        # Intenta Alpha Vantage primero
        av_result = self._load_news_av(symbol)
        if av_result is not None:
            logger.debug(f"[{symbol}] Sentimiento vía Alpha Vantage: {av_result['sentiment_score']:+.3f}")
            return av_result

        # Fallback: VADER sobre titulares de yfinance
        ticker  = yf.Ticker(symbol)
        cutoff  = datetime.now().timestamp() - 3 * 86400
        default = {"sentiment_score": 0.0, "sentiment_volume": 0}
        try:
            raw_news = ticker.news or []
            titles: list[str] = []
            for item in raw_news:
                content = item.get("content", {}) if isinstance(item.get("content"), dict) else {}
                title   = content.get("title") or item.get("title") or ""
                ts      = (
                    item.get("providerPublishTime")
                    or item.get("published")
                    or content.get("pubDate")
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
    #  Alpaca — barras históricas diarias                                  #
    # ------------------------------------------------------------------ #
    def load_alpaca_bars(
        self,
        symbol: str,
        start: str = "2010-01-01",
        end: str | None = None,
    ) -> pd.DataFrame:
        """Barras diarias desde Alpaca Markets (requiere plan activo para >5 años)."""
        cache_file = self.cache_dir / f"{symbol.upper()}_alpaca_daily.parquet"

        if cache_file.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if age < timedelta(hours=20):
                df = pd.read_parquet(cache_file)
                logger.info(f"[{symbol}] Alpaca caché local: {len(df)} filas")
                return df

        end_str = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bars = self.api.get_bars(
            symbol.upper(),
            TimeFrame.Day,
            start=start,
            end=end_str,
            feed="iex",
            adjustment="raw",
        ).df

        if bars is None or bars.empty:
            raise ValueError(f"Alpaca no devolvió datos para '{symbol}'.")

        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs(symbol.upper(), level=0)

        bars.columns = [c.lower() for c in bars.columns]
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in bars.columns]
        bars = bars[keep].copy()
        bars.index = pd.to_datetime(bars.index, utc=True)
        bars.sort_index(inplace=True)
        bars.dropna(inplace=True)

        bars.to_parquet(cache_file)
        logger.info(f"[{symbol}] Alpaca bars: {len(bars)} filas desde {start}")
        return bars

    # ------------------------------------------------------------------ #
    #  Alpha Vantage — barras históricas diarias ajustadas                 #
    # ------------------------------------------------------------------ #
    def load_alpha_vantage(
        self,
        symbol: str,
        start: str = "2010-01-01",
    ) -> pd.DataFrame:
        """
        Barras diarias ajustadas de Alpha Vantage.
        Requiere ALPHA_VANTAGE_API_KEY en .env.
        Plan gratuito: 25 llamadas/día — insuficiente para el scan completo del S&P 100.
        """
        cache_file = self.cache_dir / f"{symbol.upper()}_av_daily.parquet"

        if cache_file.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if age < timedelta(hours=20):
                df = pd.read_parquet(cache_file)
                logger.info(f"[{symbol}] Alpha Vantage caché local: {len(df)} filas")
                return df

        api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ALPHA_VANTAGE_API_KEY no configurada en .env. "
                "Regístrate en alphavantage.co para obtener una clave gratuita."
            )

        from alpha_vantage.timeseries import TimeSeries as _AV_TS
        _ts = _AV_TS(key=api_key, output_format="pandas", indexing_type="date")
        data, _ = _ts.get_daily_adjusted(symbol=symbol, outputsize="full")

        # Columnas devueltas: '1. open', '2. high', '3. low', '4. close',
        #                     '5. adjusted close', '6. volume', ...
        df = data[["1. open", "2. high", "3. low", "5. adjusted close", "6. volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df = df.astype(float)
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        df.sort_index(inplace=True)
        df.dropna(inplace=True)

        df.to_parquet(cache_file)
        logger.info(f"[{symbol}] Alpha Vantage: {len(df)} filas desde {start}")
        return df

    # ------------------------------------------------------------------ #
    #  Polygon.io — barras históricas diarias                              #
    # ------------------------------------------------------------------ #
    def load_polygon(
        self,
        symbol: str,
        start: str = "2010-01-01",
        end: str | None = None,
    ) -> pd.DataFrame:
        """
        Barras diarias de Polygon.io.
        Requiere POLYGON_API_KEY en .env y suscripción activa.
        """
        cache_file = self.cache_dir / f"{symbol.upper()}_polygon_daily.parquet"

        if cache_file.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if age < timedelta(hours=20):
                df = pd.read_parquet(cache_file)
                logger.info(f"[{symbol}] Polygon caché local: {len(df)} filas")
                return df

        api_key = os.getenv("POLYGON_API_KEY", "")
        if not api_key:
            raise ValueError(
                "POLYGON_API_KEY no configurada en .env. "
                "Crea una cuenta en polygon.io para obtener tu clave."
            )

        end_str = end or datetime.now().strftime("%Y-%m-%d")
        r = requests.get(
            f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start}/{end_str}",
            params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key},
            timeout=30,
        )
        data = r.json()

        if data.get("status") not in ("OK", "DELAYED"):
            raise ValueError(
                f"Polygon error para '{symbol}': {data.get('error') or data.get('message') or data}"
            )

        results = data.get("results", [])
        if not results:
            raise ValueError(f"Polygon: sin datos para '{symbol}'.")

        rows = [
            {
                "date":   pd.Timestamp(item["t"], unit="ms", tz="UTC"),
                "open":   float(item["o"]),
                "high":   float(item["h"]),
                "low":    float(item["l"]),
                "close":  float(item["c"]),
                "volume": float(item["v"]),
            }
            for item in results
        ]
        df = pd.DataFrame(rows).set_index("date").sort_index()
        df.dropna(inplace=True)

        df.to_parquet(cache_file)
        logger.info(f"[{symbol}] Polygon: {len(df)} filas desde {start}")
        return df

    # ------------------------------------------------------------------ #
    #  Entrada principal                                                    #
    # ------------------------------------------------------------------ #
    def load(self, symbol: str, start: str = "2010-01-01") -> pd.DataFrame:
        """
        Barras diarias limpias desde `start` hasta hoy.
        La fuente se lee de settings.json (data_source):
          yahoo         → Yahoo Finance (por defecto)
          alpaca        → Alpaca Markets historical bars
          alpha_vantage → Alpha Vantage (requiere API key)
          polygon       → Polygon.io (requiere API key de pago)
        """
        try:
            from src.config.settings_manager import settings
            source = settings.get("data_source") or "yahoo"
        except Exception:
            source = "yahoo"

        if source == "alpaca":
            df = self.load_alpaca_bars(symbol, start=start)
        elif source == "alpha_vantage":
            df = self.load_alpha_vantage(symbol, start=start)
        elif source == "polygon":
            df = self.load_polygon(symbol, start=start)
        else:
            df = self.load_yfinance(symbol, start=start)

        if len(df) < 100:
            raise ValueError(
                f"Solo {len(df)} barras disponibles para '{symbol}' "
                f"(fuente: {source}). "
                "Prueba con una fecha de inicio más reciente o un símbolo más líquido."
            )
        return df
