"""
Servidor MCP local de Alpha Vantage para Claude Code / Claude Desktop.
Expone herramientas de datos financieros usando la librería alpha_vantage.

Registro (una sola vez):
    claude mcp add alpha-vantage --scope user ^
      -e ALPHA_VANTAGE_API_KEY=TU_CLAVE ^
      "C:\\proyectos\\AlgoTrader\\.venv\\Scripts\\python.exe" ^
      "C:\\proyectos\\AlgoTrader\\mcp_alphavantage.py"

Herramientas expuestas:
    get_daily_prices      — OHLCV histórico diario ajustado
    get_news_sentiment    — Sentimiento de noticias recientes
    get_company_overview  — Datos fundamentales (P/E, sector, cap, etc.)
    get_top_movers        — Top gainers / losers del día
"""
import asyncio
import os
import sys

# Asegurar que el venv de AlgoTrader está en el path
sys.path.insert(0, r"C:\proyectos\AlgoTrader")

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="alpha-vantage",
    description="Datos financieros de Alpha Vantage: precios históricos, "
                "sentimiento de noticias, fundamentales y top movers.",
)


def _key() -> str:
    k = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not k:
        raise RuntimeError(
            "ALPHA_VANTAGE_API_KEY no configurada. "
            "Añádela al registrar el MCP: -e ALPHA_VANTAGE_API_KEY=TU_CLAVE"
        )
    return k


@mcp.tool()
def get_daily_prices(symbol: str, days: int = 30) -> dict:
    """
    Devuelve las últimas N barras OHLCV diarias ajustadas para un ticker del S&P.
    Usa precios ajustados por dividendos y splits.

    Args:
        symbol: Ticker de la acción (ej: AAPL, MSFT, NVDA)
        days:   Número de días de histórico a devolver (máx 100, default 30)
    """
    from alpha_vantage.timeseries import TimeSeries
    days = min(max(days, 1), 100)
    ts = TimeSeries(key=_key(), output_format="pandas", indexing_type="date")
    data, meta = ts.get_daily_adjusted(symbol=symbol.upper(), outputsize="compact")
    df = data[["1. open", "2. high", "3. low", "5. adjusted close", "6. volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df = df.astype(float).tail(days)
    return {
        "symbol":      symbol.upper(),
        "description": meta.get("2. Symbol", symbol),
        "last_date":   str(df.index[-1]) if not df.empty else "—",
        "last_close":  float(df["close"].iloc[-1]) if not df.empty else None,
        "rows":        df.reset_index().rename(columns={"date": "fecha"}).to_dict(orient="records"),
    }


@mcp.tool()
def get_news_sentiment(symbol: str) -> dict:
    """
    Sentimiento de las últimas noticias sobre un ticker (Alpha Vantage NEWS_SENTIMENT).
    Devuelve score medio [-1, 1], etiqueta y los 5 titulares más recientes.

    Args:
        symbol: Ticker de la acción (ej: AAPL, TSLA)
    """
    from alpha_vantage.alphaintelligence import AlphaIntelligence
    ai = AlphaIntelligence(key=_key(), output_format="json")
    data, _ = ai.get_news_sentiment(tickers=symbol.upper(), limit=20)
    feed = data.get("feed", [])
    if not feed:
        return {"symbol": symbol.upper(), "sentiment_score": 0.0, "label": "Neutral", "articles": []}

    scores = [float(item.get("overall_sentiment_score", 0.0)) for item in feed]
    avg    = sum(scores) / len(scores)

    if avg >= 0.35:
        label = "Muy positivo"
    elif avg >= 0.15:
        label = "Positivo"
    elif avg <= -0.35:
        label = "Muy negativo"
    elif avg <= -0.15:
        label = "Negativo"
    else:
        label = "Neutral"

    articles = [
        {
            "title":     item.get("title", ""),
            "source":    item.get("source", ""),
            "published": item.get("time_published", ""),
            "score":     round(float(item.get("overall_sentiment_score", 0.0)), 3),
            "label":     item.get("overall_sentiment_label", ""),
        }
        for item in feed[:5]
    ]
    return {
        "symbol":          symbol.upper(),
        "sentiment_score": round(avg, 3),
        "label":           label,
        "n_articles":      len(feed),
        "articles":        articles,
    }


@mcp.tool()
def get_company_overview(symbol: str) -> dict:
    """
    Datos fundamentales de una empresa: sector, P/E, capitalización, dividendo, 52w high/low.

    Args:
        symbol: Ticker de la acción (ej: AAPL, JPM)
    """
    from alpha_vantage.fundamentaldata import FundamentalData
    fd = FundamentalData(key=_key(), output_format="json")
    data, _ = fd.get_company_overview(symbol=symbol.upper())
    if not data or "Symbol" not in data:
        return {"error": f"Sin datos fundamentales para {symbol}"}
    keys = [
        "Symbol", "Name", "Sector", "Industry", "MarketCapitalization",
        "PERatio", "EPS", "DividendYield", "52WeekHigh", "52WeekLow",
        "AnalystTargetPrice", "Beta", "ProfitMargin", "RevenuePerShareTTM",
    ]
    return {k: data.get(k, "—") for k in keys}


@mcp.tool()
def get_top_movers() -> dict:
    """
    Top gainers y losers del mercado americano en el día de hoy.
    No requiere parámetros — devuelve los 5 mayores subidas y bajadas.
    """
    from alpha_vantage.alphaintelligence import AlphaIntelligence
    ai = AlphaIntelligence(key=_key(), output_format="json")
    data, _ = ai.get_top_gainers()
    return {
        "top_gainers": data.get("top_gainers", [])[:5],
        "top_losers":  data.get("top_losers", [])[:5],
        "most_active": data.get("most_actively_traded", [])[:5],
    }


if __name__ == "__main__":
    mcp.run()
