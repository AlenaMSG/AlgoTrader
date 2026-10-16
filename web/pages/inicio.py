import dash
import dash_ag_grid as dag
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

dash.register_page(__name__, path="/", name="Inicio", title="AlgoTrader · Inicio")


# ── Mapa ticker → nombre empresa ──────────────────────────────────────────────

COMPANY_NAMES: dict[str, str] = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AVGO": "Broadcom",
    "ORCL": "Oracle", "CSCO": "Cisco Systems", "IBM": "IBM", "INTC": "Intel",
    "TXN": "Texas Instruments", "QCOM": "Qualcomm", "ADI": "Analog Devices",
    "AMAT": "Applied Materials", "NOW": "ServiceNow", "ADBE": "Adobe",
    "CRM": "Salesforce", "INTU": "Intuit", "ACN": "Accenture", "ADP": "ADP",
    "GOOGL": "Alphabet (Google)", "META": "Meta Platforms",
    "T": "AT&T", "VZ": "Verizon",
    "AMZN": "Amazon", "TSLA": "Tesla", "MCD": "McDonald's", "NKE": "Nike",
    "LOW": "Lowe's", "HD": "Home Depot", "SBUX": "Starbucks",
    "TGT": "Target", "BKNG": "Booking Holdings",
    "PG": "Procter & Gamble", "KO": "Coca-Cola", "PEP": "PepsiCo",
    "WMT": "Walmart", "COST": "Costco", "PM": "Philip Morris",
    "MO": "Altria Group", "MDLZ": "Mondelez International",
    "CL": "Colgate-Palmolive",
    "UNH": "UnitedHealth Group", "JNJ": "Johnson & Johnson", "LLY": "Eli Lilly",
    "ABBV": "AbbVie", "MRK": "Merck", "ABT": "Abbott Laboratories",
    "TMO": "Thermo Fisher Scientific", "DHR": "Danaher",
    "BMY": "Bristol-Myers Squibb", "AMGN": "Amgen", "GILD": "Gilead Sciences",
    "ISRG": "Intuitive Surgical", "MDT": "Medtronic", "SYK": "Stryker",
    "ZTS": "Zoetis", "BDX": "Becton Dickinson", "CVS": "CVS Health",
    "CI": "Cigna", "ELV": "Elevance Health", "VRTX": "Vertex Pharmaceuticals",
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "WFC": "Wells Fargo",
    "MS": "Morgan Stanley", "GS": "Goldman Sachs", "BLK": "BlackRock",
    "SCHW": "Charles Schwab", "USB": "U.S. Bancorp",
    "PNC": "PNC Financial Services", "TFC": "Truist Financial",
    "COF": "Capital One", "C": "Citigroup", "AXP": "American Express",
    "CME": "CME Group", "SPGI": "S&P Global", "AON": "Aon",
    "MMC": "Marsh & McLennan", "V": "Visa", "MA": "Mastercard",
    "XOM": "ExxonMobil", "CVX": "Chevron", "EOG": "EOG Resources",
    "SLB": "SLB (Schlumberger)", "FCX": "Freeport-McMoRan",
    "HON": "Honeywell", "CAT": "Caterpillar", "DE": "John Deere",
    "BA": "Boeing", "GE": "GE Aerospace", "UPS": "United Parcel Service",
    "RTX": "RTX Corporation", "ETN": "Eaton", "ITW": "Illinois Tool Works",
    "FDX": "FedEx", "LIN": "Linde", "PLD": "Prologis",
    "AMT": "American Tower", "NEE": "NextEra Energy", "DUK": "Duke Energy",
    "SO": "Southern Company",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_currency(val) -> str:
    try:
        return f"${float(val):,.2f}"
    except Exception:
        return "—"


def _fmt_pct(val) -> str:
    try:
        v = float(val)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"
    except Exception:
        return "—"


def _pnl_color(val) -> str:
    try:
        return "#00bc8c" if float(val) >= 0 else "#e74c3c"
    except Exception:
        return "#aaa"


# ── KPI Card ──────────────────────────────────────────────────────────────────

def kpi_card(
    card_id: str,
    label: str,
    icon: str,
    border_color: str = "#00bc8c",
    tooltip_id: str = None,
    tooltip_text: str = None,
) -> dbc.Col:
    label_children = [html.Span(label)]
    if tooltip_id and tooltip_text:
        label_children += [
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
        ]
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Div(id=card_id, className="kpi-value text-white"),
                                html.Div(label_children, className="kpi-label mt-1"),
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
        xs=12, sm=6, xl=3,
        class_name="mb-3",
    )


# ── Column defs para la tabla de señales ──────────────────────────────────────

SIGNALS_COL_DEFS = [
    {
        "field": "symbol",
        "headerName": "Ticker",
        "filter": "agTextColumnFilter",
        "flex": 1,
        "minWidth": 80,
    },
    {
        "field": "company",
        "headerName": "Empresa",
        "filter": "agTextColumnFilter",
        "flex": 2,
        "minWidth": 140,
    },
    {
        "field": "signal",
        "headerName": "Señal",
        "filter": "agTextColumnFilter",
        "flex": 1,
        "minWidth": 130,
        "cellClassRules": {
            "badge-comprar": "params.value === 'COMPRAR'",
            "badge-vender":  "params.value === 'VENDER'",
            "badge-debil":   "params.value && (params.value.indexOf('débil') > -1 || params.value.indexOf('debil') > -1)",
            "badge-neutral": "params.value === 'NEUTRAL'",
        },
    },
    {
        "field": "price",
        "headerName": "Precio actual",
        "filter": "agNumberColumnFilter",
        "flex": 1,
        "minWidth": 110,
        "valueFormatter": {"function": "params.value != null ? '$' + Number(params.value).toFixed(2) : '—'"},
    },
    {
        "field": "pred_ret",
        "headerName": "% predicción",
        "filter": "agNumberColumnFilter",
        "flex": 1,
        "minWidth": 110,
        "valueFormatter": {"function": "params.value != null ? (params.value >= 0 ? '+' : '') + params.value.toFixed(2) + '%' : '—'"},
        "cellClassRules": {
            "pred-positive": "params.value >= 0",
            "pred-negative": "params.value < 0",
        },
    },
]


# ── Layout ────────────────────────────────────────────────────────────────────

def _scan_panel_visible() -> tuple[bool, str, str]:
    """Devuelve (visible, source_label, model_label) leyendo settings."""
    _src = {
        "yahoo":         "Yahoo Finance",
        "alpaca":        "Alpaca Markets",
        "alpha_vantage": "Alpha Vantage",
        "polygon":       "Polygon.io",
    }
    _mdl = {
        "xgb_lgb_ensemble":  "XGBoost + LightGBM",
        "xgboost":           "XGBoost",
        "lightgbm":          "LightGBM",
        "random_forest":     "Random Forest",
        "ridge":             "Ridge",
        "gradient_boosting": "Gradient Boosting",
        "xgb_rf_ensemble":   "XGBoost + RF",
    }
    try:
        from src.config.settings_manager import settings
        visible = settings.get("scan_mode") == "manual"
        src = _src.get(settings.get("data_source") or "yahoo", "Yahoo Finance")
        mdl = _mdl.get(settings.get("model_type") or "xgb_lgb_ensemble", "XGBoost + LightGBM")
    except Exception:
        visible, src, mdl = False, "Yahoo Finance", "XGBoost + LightGBM"
    return visible, src, mdl


def _strategy_banner():
    """Aviso con la estrategia principal y su estado en el backtest fijo."""
    try:
        from src.analysis.strategies import BY_ID, ESTADO_COLOR, can_trade, status
        from src.config.settings_manager import settings
        sid = settings.get("strategy")
        s = BY_ID.get(sid) or BY_ID["h1_quality_value"]
        est = status(s.id)
    except Exception:
        return html.Div()
    nota = ("Puede enviar órdenes." if can_trade(s.id)
            else "No envía órdenes hasta estar Aprobada en el backtest fijo; de momento, cartera teórica.")
    return dbc.Alert(
        dbc.Row([
            dbc.Col([
                html.I(className="fa-solid fa-chess-knight me-2"),
                html.Span("Estrategia principal: ", className="text-muted"),
                html.Strong(s.nombre),
                dbc.Badge(est, color=ESTADO_COLOR[est], className="ms-2"),
                html.Div(nota, className="text-muted", style={"fontSize": "0.78rem"}),
            ]),
            dbc.Col(dcc.Link("Ver estrategias →", href="/estrategias"), width="auto"),
        ], align="center"),
        className="py-2 mb-3",
        style={"background": "#0f1420", "color": "#ddd", "border": "1px solid #2a3a5a", "fontSize": "0.88rem"},
    )


def layout():
    visible, src_label, mdl_label = _scan_panel_visible()
    panel_style = {"border": "1px solid #1a3a1a", "background": "#0a180a"} if visible else {"display": "none"}

    return html.Div(
        [
            dcc.Interval(id="inicio-interval", interval=30_000, n_intervals=0),
            dcc.Interval(id="scan-poll-interval", interval=5_000, n_intervals=0, disabled=True),

            _strategy_banner(),

            # Panel de scan manual — siempre en DOM, oculto en modo auto
            dbc.Card(
                dbc.CardBody(
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.I(className="fa-solid fa-play-circle me-2", style={"color": "#00bc8c"}),
                                html.Span("Modo manual activado", style={"fontWeight": 600}),
                            ], className="mb-1"),
                            html.Small(
                                [f"Fuente: {src_label}  ·  Modelo: {mdl_label}  ·  ",
                                 html.A("Cambiar en Configuración", href="/configuracion",
                                        style={"color": "#00bc8c", "textDecoration": "none"})],
                                style={"color": "#888"},
                            ),
                        ]),
                        dbc.Col([
                            dbc.Button(
                                [html.I(className="fa-solid fa-play me-2"), "Lanzar análisis ahora"],
                                id="btn-run-scan",
                                color="success",
                                size="sm",
                                style={"whiteSpace": "nowrap"},
                            ),
                            html.Div(id="scan-run-status", className="mt-1",
                                     style={"fontSize": "0.8rem", "color": "#aaa"}),
                        ], width="auto", class_name="d-flex flex-column align-items-end"),
                    ], align="center"),
                ),
                style=panel_style,
                className="mb-3",
                id="scan-manual-panel",
            ),

            # Header
            dbc.Row(
                dbc.Col(
                    [
                        html.Div(
                            [
                                html.Span(className="status-dot live"),
                                html.Span("Modo simulación (sin dinero real)", className="text-muted", style={"fontSize": "0.8rem"}),
                            ],
                            className="mb-1",
                        ),
                        html.H4("Resumen de tu cuenta", className="page-title mb-0"),
                        html.Div(id="inicio-timestamp", className="page-subtitle"),
                    ]
                )
            ),

            # KPI cards
            dbc.Row(
                [
                    kpi_card(
                        "kpi-equity",
                        "Valor de tu cartera",
                        "fa-wallet",
                        "#00bc8c",
                        tooltip_id="tt-equity",
                        tooltip_text=(
                            "Es el valor total de tu cuenta ahora mismo: "
                            "todo tu efectivo más el valor actual de las acciones que tienes compradas. "
                            "Ejemplo: si tienes 5.000 $ sin invertir y acciones por valor de 3.000 $, "
                            "el valor de tu cartera es 8.000 $."
                        ),
                    ),
                    kpi_card(
                        "kpi-cash",
                        "Efectivo disponible",
                        "fa-money-bill-wave",
                        "#3498db",
                        tooltip_id="tt-cash",
                        tooltip_text=(
                            "Dinero en tu cuenta que aún no está invertido en ninguna acción. "
                            "Es lo que puedes usar para comprar acciones ahora mismo. "
                            "Cuando compras una acción, este número baja. "
                            "Cuando la vendes, vuelve a subir. "
                            "Ejemplo: 4.750 $."
                        ),
                    ),
                    kpi_card(
                        "kpi-buying-power",
                        "Capacidad de compra",
                        "fa-bolt",
                        "#9b59b6",
                        tooltip_id="tt-buying",
                        tooltip_text=(
                            "Importe máximo que puedes gastar en comprar acciones en este momento. "
                            "En modo simulación, el sistema te presta el doble de tu efectivo, "
                            "por eso suele ser mayor que el efectivo disponible. "
                            "Ejemplo: si tienes 5.000 $ en efectivo, tu capacidad de compra es 10.000 $."
                        ),
                    ),
                    kpi_card(
                        "kpi-pnl",
                        "Ganancia/Pérdida (7 días)",
                        "fa-arrow-trend-up",
                        "#e67e22",
                        tooltip_id="tt-pnl",
                        tooltip_text=(
                            "Cuánto has ganado o perdido en los últimos 7 días. "
                            "Compara el valor de tu cartera hoy con el de hace una semana. "
                            "Verde con '+' = ganaste dinero. Rojo con '-' = perdiste. "
                            "Ejemplo: +127,50 $ (+1,32%) significa que ganaste 127,50 dólares esta semana."
                        ),
                    ),
                ],
                class_name="g-3",
            ),

            # Main content
            dbc.Row(
                [
                    # Signals column
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                [
                                                    html.I(className="fa-solid fa-bell me-2 text-warning"),
                                                    html.Span("Señales del último análisis", style={"fontWeight": 600}),
                                                ]
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Button(
                                                        [html.I(className="fa-solid fa-xmark me-1"), "Limpiar filtros"],
                                                        id="btn-clear-filters",
                                                        size="sm",
                                                        color="secondary",
                                                        outline=True,
                                                        className="me-2",
                                                        style={"fontSize": "0.72rem", "padding": "2px 10px"},
                                                    ),
                                                    html.Span(id="signals-count", className="badge bg-secondary"),
                                                ],
                                                width="auto",
                                                class_name="d-flex align-items-center",
                                            ),
                                        ],
                                        align="center",
                                    )
                                ),
                                dbc.CardBody(
                                    dag.AgGrid(
                                        id="signals-grid",
                                        columnDefs=SIGNALS_COL_DEFS,
                                        rowData=[],
                                        defaultColDef={
                                            "sortable": True,
                                            "suppressMovable": True,
                                        },
                                        dashGridOptions={
                                            "animateRows": True,
                                            "headerHeight": 38,
                                            "rowHeight": 38,
                                            "tooltipShowDelay": 300,
                                            "localeText": {
                                                # Filtros generales
                                                "filterOoo": "Buscar...",
                                                "applyFilter": "Aplicar",
                                                "resetFilter": "Restablecer",
                                                "clearFilter": "Limpiar",
                                                "cancelFilter": "Cancelar",
                                                # Condiciones
                                                "andCondition": "Y",
                                                "orCondition": "O",
                                                # Filtro de texto
                                                "textFilter": "Filtro de texto",
                                                "contains": "Contiene",
                                                "notContains": "No contiene",
                                                "equals": "Igual a",
                                                "notEqual": "Distinto de",
                                                "startsWith": "Empieza por",
                                                "endsWith": "Termina en",
                                                "blank": "En blanco",
                                                "notBlank": "No en blanco",
                                                # Filtro numérico
                                                "numberFilter": "Filtro numérico",
                                                "lessThan": "Menor que",
                                                "lessThanOrEqual": "Menor o igual que",
                                                "greaterThan": "Mayor que",
                                                "greaterThanOrEqual": "Mayor o igual que",
                                                "inRange": "Entre",
                                                "inRangeStart": "Desde",
                                                "inRangeEnd": "Hasta",
                                                # Menú de columna
                                                "columns": "Columnas",
                                                "filters": "Filtros",
                                                "sortAscending": "Ordenar ascendente (A → Z)",
                                                "sortDescending": "Ordenar descendente (Z → A)",
                                                "sortUnSort": "Sin orden",
                                                "pinColumn": "Fijar columna",
                                                "pinLeft": "Fijar a la izquierda",
                                                "pinRight": "Fijar a la derecha",
                                                "noPin": "Sin fijar",
                                                "autosizeThisColumn": "Autoajustar columna",
                                                "autosizeAllColumns": "Autoajustar todas",
                                                "resetColumns": "Restablecer columnas",
                                                "expandAll": "Expandir todo",
                                                "collapseAll": "Colapsar todo",
                                                # Tabla vacía / sin resultados
                                                "noRowsToShow": "No hay señales que coincidan con los filtros seleccionados",
                                                "loadingOoo": "Cargando...",
                                            },
                                        },
                                        style={"height": "420px"},
                                    ),
                                    class_name="p-0",
                                ),
                            ],
                            class_name="h-100",
                        ),
                        xs=12, lg=7,
                        class_name="mb-3",
                    ),

                    # Stats column
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.I(className="fa-solid fa-chart-pie me-2 text-info"),
                                            html.Span("Distribución de señales", style={"fontWeight": 600}),
                                        ]
                                    ),
                                    dbc.CardBody(
                                        dcc.Graph(
                                            id="signals-pie",
                                            config={"displayModeBar": False},
                                            style={"height": "200px"},
                                        )
                                    ),
                                ],
                                class_name="mb-3",
                            ),
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        [
                                            html.I(className="fa-solid fa-info-circle me-2 text-secondary"),
                                            html.Span("Información del análisis", style={"fontWeight": 600}),
                                        ]
                                    ),
                                    dbc.CardBody(html.Div(id="scan-info")),
                                ]
                            ),
                        ],
                        xs=12, lg=5,
                        class_name="mb-3",
                    ),
                ],
                class_name="mt-3",
            ),

            # Error alert
            html.Div(id="inicio-error"),
        ]
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("kpi-equity",       "children"),
    Output("kpi-cash",         "children"),
    Output("kpi-buying-power", "children"),
    Output("kpi-pnl",          "children"),
    Output("inicio-timestamp", "children"),
    Output("inicio-error",     "children"),
    Input("inicio-interval",   "n_intervals"),
)
def update_account(n):
    from web.data import get_account_summary
    from datetime import datetime

    data = get_account_summary()
    ts = datetime.now().strftime("Actualizado a las %H:%M:%S")

    if data["error"]:
        alert = dbc.Alert(
            [html.I(className="fa-solid fa-triangle-exclamation me-2"), data["error"]],
            color="warning",
            dismissable=True,
            class_name="mt-2",
        )
        return "—", "—", "—", "—", ts, alert

    pnl_color = _pnl_color(data["pnl"])
    pnl_display = html.Span(
        [_fmt_currency(data["pnl"]), " ", html.Small(_fmt_pct(data["pnl_pct"]))],
        style={"color": pnl_color},
    )

    return (
        _fmt_currency(data["portfolio_value"]),
        _fmt_currency(data["cash"]),
        _fmt_currency(data["buying_power"]),
        pnl_display,
        ts,
        "",
    )


@callback(
    Output("signals-grid",   "rowData"),
    Output("signals-count",  "children"),
    Output("signals-pie",    "figure"),
    Output("scan-info",      "children"),
    Input("inicio-interval", "n_intervals"),
)
def update_signals(n):
    import plotly.graph_objects as go
    from web.data import get_pending_signals

    data = get_pending_signals()
    signals = data.get("signals", [])
    scan_ts = data.get("scan_timestamp", "—")

    # ── rowData para ag-grid ───────────────────────────────────────────────
    row_data = []
    for s in signals:
        signal = s.get("signal", "NEUTRAL")
        pred_ret = round(s.get("pred_return", 0) * 100, 2)
        price = s.get("stale_quote", {}).get("ask_price", None)
        sym = s["symbol"]
        row_data.append({
            "symbol": sym,
            "company": COMPANY_NAMES.get(sym, sym),
            "signal": signal,
            "price": float(price) if price else None,
            "pred_ret": pred_ret,
        })

    # ── Gráfico de tarta ───────────────────────────────────────────────────
    counts: dict[str, int] = {}
    for s in signals:
        sig = s.get("signal", "NEUTRAL")
        if "COMPRAR" in sig and "débil" not in sig and "debil" not in sig:
            key = "COMPRAR"
        elif "VENDER" in sig and "débil" not in sig and "debil" not in sig:
            key = "VENDER"
        elif "débil" in sig or "debil" in sig:
            key = "DÉBIL"
        else:
            key = "NEUTRAL"
        counts[key] = counts.get(key, 0) + 1

    pie_labels = list(counts.keys())
    pie_values = list(counts.values())
    color_map = {"COMPRAR": "#00bc8c", "VENDER": "#e74c3c", "DÉBIL": "#f39c12", "NEUTRAL": "#555"}
    colors = [color_map.get(lbl, "#888") for lbl in pie_labels]

    fig = go.Figure(
        go.Pie(
            labels=pie_labels,
            values=pie_values,
            hole=0.55,
            marker_colors=colors,
            textfont_size=11,
            showlegend=True,
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(font=dict(size=10), orientation="h", y=-0.15),
    )

    # ── Info del análisis ──────────────────────────────────────────────────
    n_buy = sum(1 for s in signals if "COMPRAR" in s.get("signal", ""))
    n_sell = sum(1 for s in signals if "VENDER" in s.get("signal", ""))
    scan_info = [
        html.Div(
            [
                html.Small("Último análisis realizado", className="text-muted d-block"),
                html.Span(scan_ts, className="scan-timestamp"),
            ],
            className="mb-3",
        ),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Div(str(len(signals)), className="fw-bold fs-5 text-white"),
                        html.Small("señales en total", className="text-muted"),
                    ],
                    xs=4,
                ),
                dbc.Col(
                    [
                        html.Div(str(n_buy), className="fw-bold fs-5", style={"color": "#00bc8c"}),
                        html.Small("recomiendan comprar", className="text-muted"),
                    ],
                    xs=4,
                ),
                dbc.Col(
                    [
                        html.Div(str(n_sell), className="fw-bold fs-5", style={"color": "#e74c3c"}),
                        html.Small("recomiendan vender", className="text-muted"),
                    ],
                    xs=4,
                ),
            ]
        ),
    ]

    return row_data, f"{len(signals)} señales", fig, scan_info


@callback(
    Output("signals-grid", "filterModel"),
    Input("btn-clear-filters", "n_clicks"),
    prevent_initial_call=True,
)
def clear_filters(_):
    return {}


# ── Scan manual ───────────────────────────────────────────────────────────────

@callback(
    Output("scan-run-status",   "children"),
    Output("scan-poll-interval","disabled"),
    Input("btn-run-scan",       "n_clicks"),
    prevent_initial_call=True,
)
def trigger_scan(_):
    from web.scan_runner import start_scan
    ok = start_scan()
    if not ok:
        return [
            html.I(className="fa-solid fa-circle-info me-1", style={"color": "#3ea6ff"}),
            "Ya hay un análisis en curso...",
        ], False
    return [
        dbc.Spinner(size="sm", color="success"),
        html.Span(" Analizando el S&P 100...", style={"marginLeft": "6px"}),
    ], False


@callback(
    Output("scan-run-status",    "children",  allow_duplicate=True),
    Output("scan-poll-interval", "disabled",  allow_duplicate=True),
    Input("scan-poll-interval",  "n_intervals"),
    prevent_initial_call=True,
)
def poll_scan(n):
    from web.scan_runner import get_status
    s = get_status()
    status = s.get("status", "idle")

    if status == "running":
        elapsed = s.get("updated_at", "")
        return [
            dbc.Spinner(size="sm", color="success"),
            html.Span(f" Analizando... ({elapsed})", style={"marginLeft": "6px"}),
        ], False

    if status == "done":
        return [
            html.I(className="fa-solid fa-circle-check me-1", style={"color": "#00bc8c"}),
            f"Análisis completado a las {s.get('updated_at', '')}. "
            "La tabla de señales se actualizará en breve.",
        ], True

    if status == "error":
        return [
            html.I(className="fa-solid fa-circle-xmark me-1", style={"color": "#e74c3c"}),
            "Error durante el análisis. Revisa los logs.",
        ], True

    return "", True


