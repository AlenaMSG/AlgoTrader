import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

dash.register_page(__name__, path="/comparacion", name="Comparación", title="AlgoTrader · Comparación")

COL_DEFS = [
    {"field": "FECHA_SCAN",      "headerName": "Fecha scan",     "minWidth": 120, "sort": "desc"},
    {"field": "symbol",          "headerName": "Símbolo",        "minWidth": 90,  "cellStyle": {"fontWeight": "700"}},
    {"field": "SEÑAL",           "headerName": "Señal",          "minWidth": 150},
    {"field": "PRED_RETURN_PCT", "headerName": "Pred. %",        "minWidth": 90,  "type": "numericColumn"},
    {"field": "PRECIO_SCAN",     "headerName": "Precio scan",    "minWidth": 110, "type": "numericColumn"},
    {"field": "PCT_REAL",        "headerName": "Ret. real %",    "minWidth": 110, "type": "numericColumn"},
    {"field": "ACERTO",          "headerName": "¿Acertó?",       "minWidth": 90},
    {"field": "PCT_ACIERTOS",    "headerName": "% aciertos",     "minWidth": 110, "type": "numericColumn"},
    {"field": "FECHA_REAL",      "headerName": "Fecha real",     "minWidth": 110},
]


def layout():
    return html.Div(
        [
            dcc.Interval(id="comp-interval", interval=120_000, n_intervals=0),

            html.H4("Comparación de predicciones", className="page-title"),
            html.Div("Predicciones históricas vs. resultados reales del mercado", className="page-subtitle"),

            # Summary cards
            dbc.Row(id="comp-kpis", class_name="g-3 mb-3"),

            # Accuracy chart
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [html.I(className="fa-solid fa-bullseye me-2"), "Precisión acumulada"]
                                ),
                                dbc.CardBody(
                                    dcc.Graph(
                                        id="comp-accuracy-chart",
                                        config={"displayModeBar": False},
                                        style={"height": "220px"},
                                    )
                                ),
                            ]
                        ),
                        xs=12, lg=8, class_name="mb-3",
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [html.I(className="fa-solid fa-chart-pie me-2"), "Aciertos por señal"]
                                ),
                                dbc.CardBody(
                                    dcc.Graph(
                                        id="comp-signal-pie",
                                        config={"displayModeBar": False},
                                        style={"height": "220px"},
                                    )
                                ),
                            ]
                        ),
                        xs=12, lg=4, class_name="mb-3",
                    ),
                ]
            ),

            # Table
            dbc.Card(
                dbc.CardBody(
                    dcc.Loading(
                        dag.AgGrid(
                            id="comp-grid",
                            columnDefs=COL_DEFS,
                            rowData=[],
                            defaultColDef={
                                "sortable": True,
                                "filter": True,
                                "resizable": True,
                            },
                            dashGridOptions={
                                "pagination": True,
                                "paginationPageSize": 50,
                            },
                            style={"height": "450px"},
                            className="ag-theme-alpine-dark",
                        ),
                        type="dot", color="#00bc8c",
                    )
                )
            ),
        ]
    )


@callback(
    Output("comp-kpis",           "children"),
    Output("comp-accuracy-chart", "figure"),
    Output("comp-signal-pie",     "figure"),
    Output("comp-grid",           "rowData"),
    Input("comp-interval",        "n_intervals"),
)
def update_comp(n):
    import plotly.graph_objects as go
    from web.data import get_predictions_log

    records = get_predictions_log()

    # Empty state
    empty_fig = go.Figure()
    empty_fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
    )
    empty_fig.add_annotation(text="Sin datos disponibles", showarrow=False, font=dict(color="#444"))

    if not records:
        kpis = [
            dbc.Col(
                dbc.Alert(
                    [html.I(className="fa-solid fa-info-circle me-2"),
                     "No hay datos en predictions_log.csv todavía. Ejecuta un análisis desde la pestaña Análisis Predictivo."],
                    color="secondary",
                ),
                xs=12,
            )
        ]
        return kpis, empty_fig, empty_fig, []

    # Metrics
    with_result = [r for r in records if r.get("ACERTO") in ("SI", "NO")]
    n_total    = len(records)
    n_resolved = len(with_result)
    n_hits     = sum(1 for r in with_result if r.get("ACERTO") == "SI")
    pct_hits   = (n_hits / n_resolved * 100) if n_resolved > 0 else 0

    kpis = [
        _kpi_col(str(n_total),      "Predicciones",       "#3498db"),
        _kpi_col(str(n_resolved),   "Con resultado",       "#9b59b6"),
        _kpi_col(f"{pct_hits:.1f}%","Tasa de acierto",    "#00bc8c" if pct_hits >= 55 else "#e74c3c"),
        _kpi_col(str(n_hits),       "Aciertos",           "#00bc8c"),
    ]

    # Accuracy over time chart
    acc_fig = go.Figure()
    if with_result:
        acc_vals = []
        hits = 0
        for i, r in enumerate(with_result):
            if r.get("ACERTO") == "SI":
                hits += 1
            acc_vals.append(hits / (i + 1) * 100)

        acc_fig.add_trace(
            go.Scatter(
                x=list(range(1, len(acc_vals) + 1)),
                y=acc_vals,
                mode="lines",
                line=dict(color="#00bc8c", width=2),
                fill="tozeroy",
                fillcolor="rgba(0,188,140,0.08)",
                name="% aciertos",
            )
        )
        acc_fig.add_hline(y=50, line_dash="dash", line_color="#555", annotation_text="50%")

    acc_fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(gridcolor="#1a1a1a", title="Predicción #"),
        yaxis=dict(gridcolor="#1a1a1a", side="right", title="%", range=[0, 100]),
        showlegend=False,
    )

    # Pie by signal type
    counts = {}
    hits_by = {}
    for r in with_result:
        sig = r.get("SEÑAL", "NEUTRAL")
        counts[sig] = counts.get(sig, 0) + 1
        if r.get("ACERTO") == "SI":
            hits_by[sig] = hits_by.get(sig, 0) + 1

    pie_labels = list(counts.keys())
    pie_values = [hits_by.get(l, 0) / counts[l] * 100 for l in pie_labels]
    color_map = {
        "COMPRAR": "#00bc8c", "VENDER": "#e74c3c",
        "COMPRAR (débil)": "#f39c12", "VENDER (débil)": "#e67e22",
    }
    colors = [color_map.get(l, "#888") for l in pie_labels]

    pie_fig = go.Figure(
        go.Pie(
            labels=pie_labels,
            values=pie_values,
            hole=0.5,
            marker_colors=colors,
            textfont_size=10,
            hovertemplate="%{label}: %{value:.1f}% acierto<extra></extra>",
        )
    )
    pie_fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(font=dict(size=9), orientation="h", y=-0.2),
    )

    return kpis, acc_fig, pie_fig, records


def _kpi_col(value: str, label: str, color: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(value, className="kpi-value", style={"color": color}),
                    html.Div(label, className="kpi-label mt-1"),
                ]
            ),
            class_name="card-kpi",
            style={"borderLeftColor": color},
        ),
        xs=6, md=3, class_name="mb-3",
    )
