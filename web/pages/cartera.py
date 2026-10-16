import dash
from dash import html, dcc, callback, Output, Input, State
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


def _kpi_card(value_text, value_color, label, icon, border_color, tooltip_id, tooltip_text, extra=None):
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
                                *( [extra] if extra is not None else [] ),
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
            dcc.Store(id="cartera-refresh-trigger", data=0),
            dcc.Store(id="cartera-positions-store", data=[]),

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
                        [
                            html.Div(
                                "Selecciona una fila para vender esa posición (total o parcial).",
                                className="scan-timestamp mb-2",
                            ),
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
                                        "rowSelection": "single",
                                    },
                                    style={"width": "100%"},
                                    className="ag-theme-alpine-dark",
                                ),
                                type="dot", color="#00bc8c",
                            ),
                        ]
                    ),
                ],
                class_name="mb-3",
            ),

            # Panel de venta manual ─────────────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader(
                        [html.I(className="fa-solid fa-hand-holding-dollar me-2"), "Vender posición"]
                    ),
                    dbc.CardBody(
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Div(id="sell-symbol-info", className="d-flex align-items-center gap-3"),
                                    xs=12, md=5,
                                ),
                                dbc.Col(
                                    dbc.InputGroup(
                                        [
                                            dbc.Input(
                                                id="sell-qty",
                                                value=0,
                                                type="number",
                                                min=0,
                                                size="sm",
                                                style={"maxWidth": "100px"},
                                            ),
                                            dbc.InputGroupText("acciones"),
                                        ],
                                        size="sm",
                                    ),
                                    xs=12, md=3,
                                    class_name="d-flex align-items-center",
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        "Selecciona una posición",
                                        id="sell-btn",
                                        size="sm",
                                        disabled=True,
                                        color="danger",
                                    ),
                                    xs=12, md="auto",
                                    class_name="d-flex align-items-center",
                                ),
                            ],
                            align="center",
                            class_name="g-2",
                        )
                    ),
                    dcc.Loading(
                        html.Div(id="sell-result", className="px-3 pb-2"),
                        type="dot", color="#e74c3c",
                    ),
                ],
                id="sell-card",
                class_name="mb-3",
                style={"display": "none"},
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
    Output("cartera-positions-store", "data"),
    Input("cartera-interval","n_intervals"),
    Input("cartera-refresh-trigger", "data"),
)
def update_cartera(n, _refresh):
    import plotly.graph_objects as go
    from datetime import datetime, timezone
    from web.data import get_positions, get_portfolio_history

    positions = get_positions()
    hist      = get_portfolio_history("1M")

    # KPI cards
    total_mv   = sum(p["market_value"]  for p in positions)
    total_upl  = sum(p["unrealized_pl"] for p in positions)
    total_gain = sum(p["unrealized_pl"] for p in positions if p["unrealized_pl"] > 0)
    total_loss = sum(p["unrealized_pl"] for p in positions if p["unrealized_pl"] < 0)
    n_pos      = len(positions)
    pnl_color  = "#00bc8c" if total_upl >= 0 else "#e74c3c"

    pnl_breakdown = html.Div(
        [
            html.Div(
                [html.I(className="fa-solid fa-caret-up"), f" +${total_gain:,.2f}"],
                className="kpi-breakdown-item",
                style={"color": "#00bc8c"},
            ),
            html.Div(
                [html.I(className="fa-solid fa-caret-down"), f" -${abs(total_loss):,.2f}"],
                className="kpi-breakdown-item",
                style={"color": "#e74c3c"},
            ),
        ],
        className="kpi-breakdown",
    )

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
            extra=pnl_breakdown,
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

    return kpis, rows, fig, positions


# ── Panel de venta: poblar al seleccionar fila ───────────────────────────────

@callback(
    Output("sell-card",        "style"),
    Output("sell-symbol-info", "children"),
    Output("sell-qty",         "value"),
    Output("sell-qty",         "max"),
    Output("sell-btn",         "children"),
    Output("sell-btn",         "disabled"),
    Output("sell-result",      "children"),
    Input("positions-grid",    "selectedRows"),
    State("cartera-positions-store", "data"),
)
def populate_sell_panel(selected_rows, positions):
    hidden = {"display": "none"}
    visible = {"display": "block"}
    empty = (hidden, [], 0, 0, "Selecciona una posición", True, "")

    if not selected_rows or not positions:
        return empty

    sym = selected_rows[0].get("symbol", "")
    pos = next((p for p in positions if p["symbol"] == sym), None)
    if not pos:
        return empty

    qty   = pos["qty"]
    price = pos["current_price"]
    pl    = pos["unrealized_pl"]
    pl_color = "#00bc8c" if pl >= 0 else "#e74c3c"

    info = [
        html.Span(sym, style={"fontWeight": "700", "fontSize": "1.1rem"}),
        html.Span(f"{qty:.0f} acciones en cartera", className="text-muted", style={"fontSize": "0.85rem"}),
        html.Span(f"Precio actual: ${price:,.2f}", className="text-muted", style={"fontSize": "0.85rem"}),
        html.Span(
            f"{'+' if pl >= 0 else ''}${pl:,.2f}",
            style={"color": pl_color, "fontWeight": "600", "fontSize": "0.85rem"},
        ),
    ]
    btn_label = [html.I(className="fa-solid fa-hand-holding-dollar me-2"), f"Vender {sym}"]

    return visible, info, qty, qty, btn_label, False, ""


# ── Ejecutar venta ────────────────────────────────────────────────────────────

@callback(
    Output("sell-result",      "children", allow_duplicate=True),
    Output("cartera-refresh-trigger", "data"),
    Input("sell-btn",          "n_clicks"),
    State("positions-grid",    "selectedRows"),
    State("sell-qty",          "value"),
    State("cartera-refresh-trigger", "data"),
    prevent_initial_call=True,
)
def execute_sell(n_clicks, selected_rows, qty, refresh_count):
    if not n_clicks or not selected_rows:
        return "", dash.no_update

    sym = selected_rows[0].get("symbol", "")

    try:
        qty = float(qty or 0)
    except (ValueError, TypeError):
        qty = 0

    if qty <= 0:
        return dbc.Alert("Indica una cantidad válida de acciones.", color="warning"), dash.no_update

    from web.data import sell_position

    result = sell_position(sym, qty)
    action = result.get("action", "skip")
    reason = result.get("reason", "")
    order  = result.get("order")

    if action == "sell" and order:
        alert = dbc.Alert(
            [
                html.I(className="fa-solid fa-check-circle me-2"),
                html.Strong(f"Venta ejecutada — {sym}: "),
                f"{order.get('qty', '?')} acciones @ ${order.get('limit_price', '?'):.2f} "
                f"· Estado: {order.get('status', '?')}",
            ],
            color="success", dismissable=True,
        )
        return alert, (refresh_count or 0) + 1
    elif action == "skip":
        return dbc.Alert(
            [html.I(className="fa-solid fa-info-circle me-2"), f"Orden omitida: {reason}"],
            color="warning", dismissable=True,
        ), dash.no_update
    else:
        return dbc.Alert(f"Error: {reason}", color="danger", dismissable=True), dash.no_update
