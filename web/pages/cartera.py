import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

dash.register_page(__name__, path="/cartera", name="Cartera", title="AlgoTrader · Cartera")


_POSITIONS_COLS = [
    {"field": "symbol",     "headerName": "Símbolo",     "flex": 0.9, "minWidth": 100, "cellStyle": {"fontWeight": "700"}},
    {
        "field": "entry_date", "headerName": "Fecha compra", "flex": 1, "minWidth": 135,
        "headerTooltip": "Fecha de la última compra ejecutada de este símbolo.",
    },
    {"field": "qty",        "headerName": "Cantidad",    "flex": 0.9, "minWidth": 110, "type": "numericColumn"},
    {
        "field": "avg_entry", "headerName": "Precio compra", "flex": 1, "minWidth": 135, "type": "numericColumn",
        "headerTooltip": "Precio de UNA acción: la media a la que compraste (si compraste varias veces, es la media ponderada). No es el total gastado — para eso está 'Total invertido'.",
    },
    {
        "field": "current_price", "headerName": "Precio actual", "flex": 1, "minWidth": 135, "type": "numericColumn",
        "headerTooltip": "Precio de UNA acción ahora mismo (cotización en vivo).",
    },
    {
        "field": "total_cost", "headerName": "Total invertido", "flex": 1.2, "minWidth": 155, "type": "numericColumn",
        "headerTooltip": "Lo que gastaste en total comprando este símbolo: Cantidad × Precio compra. No cambia con el mercado.",
    },
    {
        "field": "market_value", "headerName": "Valor de la posición", "flex": 1.3, "minWidth": 175, "type": "numericColumn",
        "headerTooltip": "Cuánto vale HOY toda la posición: Cantidad × Precio actual (no es el precio de una acción, es el total). Compáralo con 'Total invertido': si es mayor, vas ganando.",
    },
    {
        "field": "unrealized_pl",
        "headerName": "Ganancia / Pérdida",
        "flex": 1.2, "minWidth": 165,
        "type": "numericColumn",
        "headerTooltip": "Lo que ganarías o perderías si vendieras esta posición ahora mismo. Aún no es dinero real hasta que vendas.",
        "valueFormatter": {
            "function": "(params.value >= 0 ? '+$' : '-$') + Math.abs(params.value).toFixed(2)"
        },
        "cellClassRules": {
            "badge-comprar": "params.value > 0",
            "badge-vender":  "params.value < 0",
        },
    },
]


def _kpi_card(value_text, value_color, label, icon, border_color, tooltip_id, tooltip_text):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Div(value_text, className="kpi-value", style={"color": value_color}),
                                html.Div(
                                    [
                                        html.Span(label),
                                        html.I(
                                            className="fa-solid fa-circle-info kpi-info-icon ms-1",
                                            id=tooltip_id,
                                        ),
                                        dbc.Tooltip(
                                            tooltip_text,
                                            target=tooltip_id,
                                            placement="bottom",
                                            style={"maxWidth": "280px", "fontSize": "0.8rem"},
                                        ),
                                    ],
                                    className="kpi-label mt-1",
                                ),
                            ],
                            width=9,
                        ),
                        dbc.Col(
                            html.I(className=f"fa-solid {icon} kpi-icon"),
                            width=3,
                            class_name="d-flex align-items-center justify-content-end",
                        ),
                    ],
                    align="center",
                )
            ),
            class_name="card-kpi h-100",
            style={"borderLeftColor": border_color},
        ),
        xs=12, sm=4, class_name="mb-3",
    )


def layout():
    return html.Div(
        [
            dcc.Interval(id="cartera-interval", interval=180_000, n_intervals=0),

            html.H4("Mi Cartera", className="page-title"),
            html.Div("Posiciones abiertas en Alpaca Paper Trading", className="page-subtitle"),

            # Summary cards
            dbc.Row(id="cartera-kpis", class_name="g-3 mb-3"),

            # Positions table (ancho completo: son 8 columnas)
            dbc.Card(
                [
                    dbc.CardHeader(
                        [html.I(className="fa-solid fa-table me-2"), "Posiciones abiertas"]
                    ),
                    dbc.CardBody(
                        dcc.Loading(
                            dag.AgGrid(
                                id="positions-grid",
                                columnDefs=_POSITIONS_COLS,
                                rowData=[],
                                defaultColDef={"sortable": True, "resizable": True, "filter": True},
                                dashGridOptions={
                                    "animateRows": True,
                                    "pagination": True,
                                    "paginationPageSize": 20,
                                    "suppressColumnVirtualisation": True,
                                    "domLayout": "autoHeight",
                                },
                                style={"width": "100%"},
                                className="ag-theme-alpine-dark",
                            ),
                            type="dot", color="#00bc8c",
                        )
                    ),
                ],
                class_name="mb-3",
            ),

            # Equity curve (ancho completo, debajo de la tabla)
            dbc.Card(
                [
                    dbc.CardHeader(
                        [html.I(className="fa-solid fa-chart-line me-2"),
                         "Evolución del valor de la cuenta"]
                    ),
                    dbc.CardBody(
                        [
                            html.Div(
                                "Efectivo + posiciones, día a día (último mes)",
                                className="scan-timestamp mb-2",
                            ),
                            dcc.Loading(
                                dcc.Graph(
                                    id="equity-curve",
                                    config={"displayModeBar": False},
                                    style={"height": "270px"},
                                ),
                                type="dot", color="#00bc8c",
                            ),
                        ]
                    ),
                ],
                class_name="mb-3",
            ),
        ]
    )


@callback(
    Output("cartera-kpis",   "children"),
    Output("positions-grid", "rowData"),
    Output("equity-curve",   "figure"),
    Input("cartera-interval","n_intervals"),
)
def update_cartera(n):
    import plotly.graph_objects as go
    from datetime import datetime, timezone
    from web.data import get_positions, get_portfolio_history

    positions = get_positions()
    hist      = get_portfolio_history("1M")

    # KPI cards
    total_mv  = sum(p["market_value"]   for p in positions)
    total_upl = sum(p["unrealized_pl"]  for p in positions)
    n_pos     = len(positions)
    pnl_color = "#00bc8c" if total_upl >= 0 else "#e74c3c"

    kpis = [
        _kpi_card(
            f"${total_mv:,.2f}", "#fff",
            "Valor de las posiciones", "fa-chart-pie", "#3498db",
            "kpi-mv-tt",
            "Cuánto valen HOY, en total, las acciones que tienes compradas "
            "(cantidad × precio actual de cada una). No incluye el efectivo "
            "que tengas sin invertir — solo lo que está metido en bolsa.",
        ),
        _kpi_card(
            f"{'+' if total_upl >= 0 else ''}${total_upl:,.2f}", pnl_color,
            "Ganancia / Pérdida no realizada", "fa-scale-balanced", pnl_color,
            "kpi-upl-tt",
            "Cuánto ganarías o perderías si vendieras TODO ahora mismo: la "
            "diferencia entre lo que pagaste por cada acción y lo que vale "
            "hoy. Se llama 'no realizada' porque aún no has vendido — sube y "
            "baja con el precio en tiempo real. Verde = ganancia, rojo = "
            "pérdida.",
        ),
        _kpi_card(
            str(n_pos), "#fff",
            "Posiciones abiertas", "fa-layer-group", "#9b59b6",
            "kpi-npos-tt",
            "Número de acciones distintas que tienes compradas ahora mismo "
            "(por ejemplo, si tienes AAPL, TSLA y NVDA, aquí pone 3).",
        ),
    ]

    # Positions table
    rows = [
        {
            "symbol":         p["symbol"],
            "entry_date":     p.get("entry_date", "—"),
            "qty":            f"{p['qty']:.0f}",
            "avg_entry":      f"${p['avg_entry']:.2f}",
            "current_price":  f"${p['current_price']:.2f}",
            "total_cost":     f"${p['avg_entry'] * p['qty']:,.2f}",
            "market_value":   f"${p['market_value']:,.2f}",
            "unrealized_pl":  p["unrealized_pl"],
        }
        for p in sorted(positions, key=lambda x: abs(x["unrealized_pl"]), reverse=True)
    ]

    # Equity curve
    timestamps = hist.get("timestamps", [])
    equity     = hist.get("equity", [])

    fig = go.Figure()
    if timestamps and equity:
        from datetime import datetime, timezone
        dates    = [datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d") for t in timestamps]
        eq_clean = [e for e in equity if e is not None]

        fig.add_trace(
            go.Scatter(
                x=dates, y=[e if e is not None else None for e in equity],
                mode="lines",
                line=dict(color="#00bc8c", width=2),
                connectgaps=True,
                name="Equity",
                hovertemplate="%{x}<br>$%{y:,.2f}<extra></extra>",
            )
        )
        # Encuadrar el eje Y a la variación real: con "tozeroy" (0 -> 100k) la
        # curva se ve como una línea plana, ya que la cartera se mueve poco
        # respecto al total. Aquí se ajusta el rango a los datos reales.
        if eq_clean:
            lo, hi = min(eq_clean), max(eq_clean)
            pad = max((hi - lo) * 0.15, hi * 0.001, 1)
            fig.update_yaxes(range=[lo - pad, hi + pad])
    else:
        fig.add_annotation(text="Sin historial disponible", showarrow=False, font=dict(color="#555"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(gridcolor="#1a1a1a"),
        yaxis=dict(gridcolor="#1a1a1a", side="right", tickprefix="$"),
        showlegend=False,
    )

    return kpis, rows, fig
