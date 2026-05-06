from datetime import datetime, timedelta, timezone
import pandas as pd
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

PAPER_URL = "https://paper-api.alpaca.markets"


class DataFetcher:
    def __init__(self, api_key: str, secret_key: str):
        self.api = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url=PAPER_URL,
        )

    def fetch_bars(self, symbol: str, days: int = 60) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        # Add extra buffer so we always get enough bars after market-hours gaps
        start = end - timedelta(days=days + 10)

        bars = self.api.get_bars(
            symbol,
            TimeFrame.Hour,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            feed="iex",          # IEX = free tier; change to 'sip' with paid plan
            adjustment="raw",
        ).df

        # get_bars may return a MultiIndex (symbol, timestamp) for batch calls
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs(symbol, level=0)

        bars.index = pd.to_datetime(bars.index, utc=True)
        bars.sort_index(inplace=True)

        # Keep only the last `days` worth of trading hours
        cutoff = end - timedelta(days=days)
        bars = bars[bars.index >= cutoff]

        if len(bars) < 50:
            raise ValueError(
                f"Solo {len(bars)} barras disponibles para {symbol}. "
                "Prueba con un símbolo más líquido o amplía el rango de días."
            )
        return bars

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
            # Fallback: use latest bar close as both sides
            bar = self.api.get_latest_bar(symbol)
            price = float(bar.c)
            return {
                "ask_price": price,
                "ask_size":  0,
                "bid_price": price,
                "bid_size":  0,
            }
