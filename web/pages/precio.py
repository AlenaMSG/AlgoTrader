import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

dash.register_page(__name__, path="/precio", name="Precio", title="AlgoTrader · Precio")

from src.data.sp100 import SP100_SYMBOLS

INTERVALS = [
    {"label": "Diario",  "value": "1d"},
    {"label": "1 Hora",  "value": "1h"},
    {"label": "15 Min",  "value": "15m"},
]

PERIODS = [
    {"label": "1 mes",   "value": "1mo"},
    {"label": "3 meses", "value": "3mo"},
    {"label": "6 meses", "value": "6mo"},
    {"label": "1 año",   "value": "1y"},
    {"label": "2 años",  "value": "2y"},
]


def layout():
    return html.Div(
        [
            html.H4("Evolución del precio", className="page-title"),
            html.Div("Gráfico de velas interactivo", className="page-subtitle"),

            # Controls
            dbc.Card(
                dbc.CardBody(
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("Símbolo", className="kpi-label mb-1"),
                                    dcc.Dropdown(
                                        id="precio-symbol",
                                        options=[{"label": s, "value": s} for s in sorted(SP100_SYMBOLS)],
                                        value="AAPL",
                                        clearable=False,
                                        className="dash-dark-dropdown",
                                    ),
                                ],
                                xs=12, md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Intervalo", className="kpi-label mb-1"),
                                    dbc.ButtonGroup(
                                        [
                                            dbc.Button(i["label"], id=f"iv-{i['value']}", outline=True,
                                                       color="success", size="sm", n_clicks=0)
                                            for i in INTERVALS
                                        ],
                                        id="interval-group",
                                    ),
                                ],
                                xs=12, md=4,
                                class_name="d-flex flex-column",
                            ),
                            dbc.Col(
                                [
                                    html.Label("Periodo", className="kpi-label mb-1"),
                                    dbc.ButtonGroup(
                                        [
                                            dbc.Button(p["label"], id=f"pd-{p['value']}", outline=True,
                                                       color="info", size="sm", n_clicks=0)
                                            for p in PERIODS
                                        ],
                                        id="period-group",
                                    ),
                                ],
                                xs=12, md=4,
                                class_name="d-flex flex-column",
                            ),
                        ],
                        class_name="g-3",
                    )
                ),
                class_name="mb-3",
            ),

            # Chart
            dbc.Card(
                dbc.CardBody(
                    [
                        dcc.Loading(
                            dcc.Graph(
                                id="candlestick-chart",
                                config={"displayModeBar": True, "scrollZoom": True},
                                style={"height": "480px"},
                            ),
                            type="dot",
                            color="#00bc8c",
                        ),
                    ]
                ),
                class_name="mb-3",
            ),

            # Volume chart
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(
                        id="volume-chart",
                        config={"displayModeBar": False},
                        style={"height": "140px"},
                    )
                ),
            ),

            # Hidden stores for selected interval/period
            dcc.Store(id="selected-interval", data="1d"),
            dcc.Store(id="selected-period",   data="6mo"),
        ]
    )


@callback(
    Output("selected-interval", "data"),
    [Input(f"iv-{i['value']}", "n_clicks") for i in INTERVALS],
    prevent_initial_call=True,
)
def set_interval(*args):
    ctx = dash.callback_context
    if not ctx.triggered:
        return "1d"
    btn_id = ctx.triggered[0]["prop_id"].split(".")[0]
    return btn_id.replace("iv-", "")


@callback(
    Output("selected-period", "data"),
    [Input(f"pd-{p['value']}", "n_clicks") for p in PERIODS],
    prevent_initial_call=True,
)
def set_period(*args):
    ctx = dash.callback_context
    if not ctx.triggered:
        return "6mo"
    btn_id = ctx.triggered[0]["prop_id"].split(".")[0]
    return btn_id.replace("pd-", "")


@callback(
    Output("candlestick-chart", "figure"),
    Output("volume-chart",      "figure"),
    Input("precio-symbol",      "value"),
    Input("selected-interval",  "data"),
    Input("selected-period",    "data"),
)
def update_chart(symbol, interval, period):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from web.data import get_candlestick_data

    data = get_candlestick_data(symbol or "AAPL", period=period, interval=interval)

    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")

    if data.get("error"):
        empty_fig.add_annotation(text=data["error"], showarrow=False, font=dict(color="#e74c3c", size=14))
        return empty_fig, empty_fig

    dates  = data["dates"]
    closes = data["close"]

    # Candlestick
    arrows = ["▲" if c >= o else "▼" for c, o in zip(closes, data["open"])]

    candle_fig = go.Figure()
    candle_fig.add_trace(
        go.Candlestick(
            x=dates,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=closes,
            name=symbol,
            increasing_line_color="#00bc8c",
            decreasing_line_color="#e74c3c",
            increasing_fillcolor="#00bc8c",
            decreasing_fillcolor="#e74c3c",
            customdata=arrows,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Apertura: %{open:.2f}<br>"
                "Máximo: %{high:.2f}<br>"
                "Mínimo: %{low:.2f}<br>"
                "Cierre: %{close:.2f} %{customdata}"
                "<extra></extra>"
            ),
        )
    )

    # Moving averages
    import pandas as pd
    s = pd.Series(closes)
    for window, color, name in [(20, "#3498db", "MA20"), (50, "#f39c12", "MA50")]:
        ma = s.rolling(window).mean()
        candle_fig.add_trace(
            go.Scatter(
                x=dates, y=ma.tolist(),
                line=dict(color=color, width=1.2),
                name=name, opacity=0.8,
            )
        )

    candle_fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font=dict(size=10)),
        title=dict(text=f"{symbol} · {interval}", font=dict(size=13), x=0.01),
        xaxis=dict(gridcolor="#1a1a1a", showgrid=True),
        yaxis=dict(gridcolor="#1a1a1a", showgrid=True, side="right"),
    )

    # Volume
    vol_colors = [
        "#00bc8c" if c >= o else "#e74c3c"
        for c, o in zip(data["close"], data["open"])
    ]
    vol_fig = go.Figure(
        go.Bar(
            x=dates,
            y=data["volume"],
            marker_color=vol_colors,
            opacity=0.7,
            name="Volumen",
        )
    )
    vol_fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(gridcolor="#1a1a1a", showticklabels=False),
        yaxis=dict(gridcolor="#1a1a1a", side="right", tickformat=".2s"),
        showlegend=False,
    )

    return candle_fig, vol_fig
