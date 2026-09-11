import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

dash.register_page(__name__, path="/historial", name="Historial", title="AlgoTrader · Historial")

COL_DEFS = [
    {"field": "timestamp",      "headerName": "Fecha/Hora",     "minWidth": 160, "sort": "desc"},
    {"field": "symbol",         "headerName": "Símbolo",        "minWidth": 90,
     "cellStyle": {"fontWeight": "700"}},
    {
        "field": "signal", "headerName": "Señal", "minWidth": 160,
        "cellClassRules": {
            "badge-comprar": "params.value === 'COMPRAR'",
            "badge-vender":  "params.value === 'VENDER'",
            "badge-debil":   "params.value && params.value.includes('débil')",
            "badge-neutral": "params.value === 'NEUTRAL'",
        },
    },
    {"field": "pred_return_pct","headerName": "Pred. Ret. %",   "minWidth": 110, "type": "numericColumn"},
    {"field": "dir_acc_pct",    "headerName": "Dir. Acc. %",    "minWidth": 110, "type": "numericColumn"},
    {"field": "ask",            "headerName": "Ask",            "minWidth": 90,  "type": "numericColumn"},
    {"field": "sentiment_score","headerName": "Sentiment",      "minWidth": 100, "type": "numericColumn"},
    {"field": "pc_ratio",       "headerName": "P/C Ratio",      "minWidth": 100, "type": "numericColumn"},
    {
        "field": "model_type", "headerName": "Modelo", "minWidth": 160,
        "headerTooltip": "Modelo de IA activo en Configuración cuando se generó esta señal.",
    },
    {
        "field": "data_source", "headerName": "Fuente de datos", "minWidth": 140,
        "headerTooltip": "De dónde venían los precios históricos usados para entrenar/predecir en ese momento.",
    },
]


def layout():
    return html.Div(
        [
            html.H4("Historial de scans", className="page-title"),
            html.Div("Registro completo de señales generadas por el scanner S&P100", className="page-subtitle"),

            # Filters
            dbc.Card(
                dbc.CardBody(
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("Filtrar por señal", className="kpi-label mb-1"),
                                    dcc.Dropdown(
                                        id="hist-signal-filter",
                                        options=[
                                            {"label": "Todas",          "value": "ALL"},
                                            {"label": "COMPRAR",        "value": "COMPRAR"},
                                            {"label": "VENDER",         "value": "VENDER"},
                                            {"label": "Débiles",        "value": "DEBIL"},
                                        ],
                                        value="ALL",
                                        clearable=False,
                                    ),
                                ],
                                xs=12, md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Buscar símbolo", className="kpi-label mb-1"),
                                    dbc.Input(
                                        id="hist-symbol-search",
                                        placeholder="Ej: AAPL",
                                        debounce=True,
                                        type="text",
                                    ),
                                ],
                                xs=12, md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label(" ", className="kpi-label mb-1 d-block"),
                                    dbc.Button(
                                        [html.I(className="fa-solid fa-rotate-right me-2"), "Actualizar"],
                                        id="hist-refresh",
                                        color="outline-success",
                                        size="sm",
                                    ),
                                ],
                                xs=12, md=4,
                                class_name="d-flex align-items-end",
                            ),
                        ],
                        class_name="g-3",
                    )
                ),
                class_name="mb-3",
            ),

            # Table
            dbc.Card(
                dbc.CardBody(
                    dcc.Loading(
                        dag.AgGrid(
                            id="hist-grid",
                            columnDefs=COL_DEFS,
                            rowData=[],
                            defaultColDef={
                                "sortable": True,
                                "filter": True,
                                "resizable": True,
                                "floatingFilter": False,
                            },
                            dashGridOptions={
                                "pagination": True,
                                "paginationPageSize": 50,
                                "animateRows": True,
                                "rowSelection": "single",
                            },
                            style={"height": "500px"},
                            className="ag-theme-alpine-dark",
                        ),
                        type="dot", color="#00bc8c",
                    )
                ),
                class_name="mb-3",
            ),

            html.Div(id="hist-row-count", className="scan-timestamp text-end"),
        ]
    )


@callback(
    Output("hist-grid",      "rowData"),
    Output("hist-row-count", "children"),
    Input("hist-refresh",        "n_clicks"),
    Input("hist-signal-filter",  "value"),
    Input("hist-symbol-search",  "value"),
)
def update_hist(n_clicks, signal_filter, symbol_search):
    from web.data import get_scan_log

    records = get_scan_log()

    if signal_filter and signal_filter != "ALL":
        if signal_filter == "DEBIL":
            records = [r for r in records if "débil" in str(r.get("signal", "")).lower() or "debil" in str(r.get("signal", "")).lower()]
        else:
            records = [r for r in records if signal_filter in str(r.get("signal", "")).upper() and "DÉBIL" not in str(r.get("signal", "")).upper() and "DEBIL" not in str(r.get("signal", "")).upper()]

    if symbol_search:
        sym = symbol_search.strip().upper()
        records = [r for r in records if sym in str(r.get("symbol", "")).upper()]

    return records, f"{len(records)} registros"
