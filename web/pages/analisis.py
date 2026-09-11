import dash
from dash import html, dcc, callback, Output, Input, State, ALL, MATCH
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

dash.register_page(__name__, path="/analisis", name="Análisis", title="AlgoTrader · Análisis")

from src.data.sp100 import SP100_SYMBOLS

_SYMBOL_OPTIONS = [{"label": "Todos (S&P100)", "value": "__ALL__"}] + [
    {"label": s, "value": s} for s in sorted(SP100_SYMBOLS)
]

FEATURE_TOOLTIPS = {
    "log_ret_1d":        "Retorno logarítmico del último día.",
    "log_ret_5d":        "Retorno logarítmico de los últimos 5 días.",
    "log_ret_20d":       "Retorno logarítmico de los últimos 20 días (aprox. 1 mes).",
    "sma20":             "Media móvil simple de los últimos 20 días.",
    "sma50":             "Media móvil simple de los últimos 50 días.",
    "sma_ratio":         "SMA20 dividida entre SMA50: por encima de 1 indica tendencia alcista, por debajo, bajista.",
    "price_sma20":       "Precio actual dividido entre su media móvil de 20 días.",
    "macd":              "MACD: diferencia entre las medias móviles exponenciales de 12 y 26 días.",
    "macd_signal":       "Línea de señal del MACD (media exponencial de 9 días del propio MACD).",
    "macd_hist":         "Histograma MACD: diferencia entre el MACD y su línea de señal; anticipa cambios de tendencia.",
    "rsi":               "RSI (14 días), índice de fuerza relativa: por encima de 70 sugiere sobrecompra, por debajo de 30, sobreventa.",
    "bb_upper":          "Banda superior de Bollinger (media móvil + 2 desviaciones típicas).",
    "bb_lower":          "Banda inferior de Bollinger (media móvil − 2 desviaciones típicas).",
    "bb_mid":            "Banda media de Bollinger (media móvil simple de 20 días).",
    "bb_bwidth":         "Ancho de las Bandas de Bollinger: mide cuánta volatilidad hay en este momento.",
    "bb_pct":            "Posición del precio dentro de las Bandas de Bollinger (0 = banda inferior, 1 = banda superior).",
    "atr":               "ATR (14 días), rango medio real: mide la volatilidad media del precio.",
    "vol_sma20":         "Media móvil del volumen negociado en los últimos 20 días.",
    "vol_ratio":         "Volumen actual dividido entre su media de 20 días; un valor alto indica actividad inusual.",
    "hl_range":          "Rango intradía (máximo − mínimo de la sesión) dividido entre el precio de cierre.",
    "close":             "Precio de cierre de la última sesión.",
    "days_to_earnings":  "Días que faltan hasta la próxima publicación de resultados (earnings) de la empresa.",
    "is_earnings_week":  "Indica si la publicación de resultados cae dentro de los próximos 5 días.",
    "days_to_exdiv":     "Días que faltan hasta la próxima fecha ex-dividendo.",
    "is_pre_exdiv":      "Indica si la fecha ex-dividendo cae dentro de los próximos 5 días.",
    "vix":               "Nivel del índice VIX: mide la volatilidad esperada del mercado (el 'índice del miedo').",
    "vix_chg_5d":        "Variación del índice VIX en los últimos 5 días.",
    "rel_ret_5d":        "Retorno del activo en los últimos 5 días, comparado con el del S&P 500 (SPY).",
    "rel_ret_20d":       "Retorno del activo en los últimos 20 días, comparado con el del S&P 500 (SPY).",
}

BACKTEST_TOOLTIPS = {
    "Win rate":    "Porcentaje de operaciones del backtest que resultaron ganadoras.",
    "Sharpe":      "Ratio de Sharpe: rentabilidad obtenida por unidad de riesgo asumido. Cuanto más alto, mejor.",
    "Max DD":      "Máxima caída (drawdown): la mayor pérdida sufrida desde un máximo hasta el siguiente mínimo.",
    "CAGR":        "Tasa de crecimiento anual compuesta: rentabilidad media anualizada de la estrategia.",
    "Alpha":       "Rentabilidad extra de la estrategia frente a simplemente comprar y mantener (Buy & Hold).",
    "B&H return":  "Buy & Hold: retorno que se habría obtenido comprando el activo al inicio y manteniéndolo, sin operar.",
}

OOS_MAE_TOOLTIP = (
    "Error absoluto medio fuera de muestra: cuánto se equivoca en promedio el modelo al predecir el "
    "retorno, medido con datos que no usó para entrenar."
)


def _info_icon(tip_id: str, text: str):
    return html.Span(
        [
            html.I(className="fa-solid fa-circle-info kpi-info-icon ms-1", id=tip_id),
            dbc.Tooltip(text, target=tip_id, placement="top", style={"maxWidth": "280px", "fontSize": "0.78rem"}),
        ]
    )


_TABLE_COLS = [
    {"field": "symbol",     "headerName": "Acción",            "flex": 0.8, "minWidth": 90,  "cellStyle": {"fontWeight": "700"}},
    {
        "field": "signal",
        "headerName": "Señal",
        "flex": 1.2, "minWidth": 170,
        "cellClassRules": {
            "badge-comprar": "params.value === 'COMPRAR'",
            "badge-vender":  "params.value === 'VENDER'",
            "badge-debil":   "params.value && params.value.includes('débil')",
            "badge-neutral": "params.value === 'NEUTRAL'",
        },
    },
    {"field": "pred_pct",   "headerName": "Ganancia esperada", "flex": 1,   "minWidth": 140, "type": "numericColumn"},
    {"field": "price",      "headerName": "Precio",            "flex": 0.8, "minWidth": 90,  "type": "numericColumn"},
    {"field": "confidence", "headerName": "Confianza",         "flex": 0.8, "minWidth": 100},
    {"field": "status",     "headerName": "Estado",            "flex": 1,   "minWidth": 110},
]


# ─────────────────────────────────────────────────────────────────────────────

def layout():
    return html.Div(
        [
            # State stores
            dcc.Store(id="analisis-symbols-store", data=[]),
            dcc.Store(id="analisis-results-store", data=[]),

            html.H4("Análisis Predictivo", className="page-title"),
            html.Div(
                "Predice el retorno esperado (%) del próximo día hábil para los símbolos seleccionados",
                className="page-subtitle",
            ),

            # ── Cabecera: todos los filtros visibles ─────────────────────
            dbc.Card(
                dbc.CardBody(
                    [
                        # Fila 1: Símbolos
                        html.Div("SÍMBOLOS", className="kpi-label mb-2"),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dcc.Dropdown(
                                        id="analisis-combo",
                                        options=_SYMBOL_OPTIONS,
                                        value="__ALL__",
                                        clearable=False,
                                        placeholder="Símbolo...",
                                    ),
                                    xs=12, sm=6, md=3,
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        [html.I(className="fa-solid fa-plus me-1"), "Agregar"],
                                        id="analisis-add-btn",
                                        color="primary",
                                        outline=True,
                                        size="sm",
                                    ),
                                    xs="auto",
                                    class_name="d-flex align-items-center",
                                ),
                                dbc.Col(
                                    html.Div(
                                        id="analisis-chips",
                                        className="d-flex flex-wrap gap-2 align-items-center",
                                    ),
                                    class_name="d-flex align-items-center flex-grow-1",
                                ),
                            ],
                            align="center",
                            class_name="g-2 mb-3",
                        ),

                        html.Hr(className="my-2"),

                        # Fila 2: Periodo + Umbral + Ejecutar + Importe
                        dbc.Row(
                            [
                                # Periodo
                                dbc.Col(
                                    [
                                        html.Div("PERIODO", className="kpi-label mb-1"),
                                        dbc.InputGroup(
                                            [
                                                dbc.InputGroupText("Desde", style={"fontSize": "0.78rem"}),
                                                dbc.Input(
                                                    id="analisis-desde",
                                                    value="01-01-2022",
                                                    placeholder="DD-MM-AAAA",
                                                    size="sm",
                                                    style={"maxWidth": "110px"},
                                                ),
                                                dbc.InputGroupText("Hasta", style={"fontSize": "0.78rem"}),
                                                dbc.Input(
                                                    id="analisis-hasta",
                                                    placeholder="hoy",
                                                    size="sm",
                                                    style={"maxWidth": "110px"},
                                                ),
                                            ],
                                            size="sm",
                                        ),
                                    ],
                                    xs=12, md=4,
                                ),
                                # Umbral
                                dbc.Col(
                                    [
                                        html.Div("UMBRAL SEÑAL", className="kpi-label mb-1"),
                                        dbc.InputGroup(
                                            [
                                                dbc.Input(
                                                    id="analisis-threshold",
                                                    value="0.5",
                                                    type="number",
                                                    min=0, max=5, step=0.1,
                                                    size="sm",
                                                    style={"maxWidth": "70px"},
                                                ),
                                                dbc.InputGroupText("% mín. para Comprar/Vender"),
                                            ],
                                            size="sm",
                                        ),
                                    ],
                                    xs=12, md=3,
                                ),
                                # Ejecutar + Importe
                                dbc.Col(
                                    [
                                        html.Div("EJECUCIÓN", className="kpi-label mb-1"),
                                        dbc.Row(
                                            [
                                                dbc.Col(
                                                    dbc.Switch(
                                                        id="analisis-auto-exec",
                                                        label="Ejecutar Compra/Venta",
                                                        value=False,
                                                        class_name="mb-0",
                                                    ),
                                                    xs=12, sm="auto",
                                                ),
                                                dbc.Col(
                                                    dbc.Collapse(
                                                        dbc.InputGroup(
                                                            [
                                                                dbc.InputGroupText("$"),
                                                                dbc.Input(
                                                                    id="analisis-trade-amount",
                                                                    value="1000",
                                                                    type="number",
                                                                    size="sm",
                                                                    style={"maxWidth": "80px"},
                                                                ),
                                                                dbc.InputGroupText("por op."),
                                                            ],
                                                            size="sm",
                                                        ),
                                                        id="exec-amount-collapse",
                                                        is_open=False,
                                                    ),
                                                    xs=12, sm="auto",
                                                    class_name="d-flex align-items-center",
                                                ),
                                            ],
                                            align="center",
                                            class_name="g-1",
                                        ),
                                    ],
                                    xs=12, md=3,
                                ),
                                # Botones
                                dbc.Col(
                                    [
                                        html.Div(" ", className="kpi-label mb-1"),
                                        dbc.Stack(
                                            [
                                                dbc.Button(
                                                    [html.I(className="fa-solid fa-brain me-1"), "Predecir Señal"],
                                                    id="analisis-run-btn",
                                                    color="primary",
                                                    size="sm",
                                                ),
                                                dbc.Button(
                                                    [html.I(className="fa-solid fa-rotate-right me-1"),
                                                     "Actualizar resultados reales"],
                                                    id="analisis-update-btn",
                                                    color="success",
                                                    outline=True,
                                                    size="sm",
                                                ),
                                            ],
                                            direction="horizontal",
                                            gap=2,
                                            class_name="justify-content-end",
                                        ),
                                    ],
                                    xs=12, md="auto",
                                    class_name="d-flex flex-column justify-content-end ms-auto",
                                    style={"textAlign": "right"},
                                ),
                            ],
                            align="end",
                            class_name="g-3",
                        ),
                    ]
                ),
                class_name="mb-3",
            ),

            # ── Status / progress ─────────────────────────────────────────
            html.Div(id="analisis-status", className="scan-timestamp mb-2"),

            # ── Tabla de resultados ───────────────────────────────────────
            dbc.Card(
                dbc.CardBody(
                    dcc.Loading(
                        dag.AgGrid(
                            id="analisis-grid",
                            columnDefs=_TABLE_COLS,
                            rowData=[],
                            defaultColDef={"sortable": True, "resizable": True, "filter": True},
                            dashGridOptions={
                                "rowSelection": "single",
                                "animateRows": True,
                                "pagination": True,
                                "paginationPageSize": 20,
                            },
                            style={"height": "280px"},
                            className="ag-theme-alpine-dark",
                        ),
                        type="dot",
                        color="#00bc8c",
                    )
                ),
                class_name="mb-3",
                id="analisis-grid-card",
            ),

            # ── Cards de detalle (aparecen al seleccionar una fila) ───────
            dbc.Row(
                [
                    # Señal de trading
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [html.I(className="fa-solid fa-signal me-2"), "Señal de trading"]
                                ),
                                dbc.CardBody(html.Div(id="detail-signal")),
                            ],
                            class_name="h-100",
                        ),
                        xs=12, md=6, lg=3, class_name="mb-3",
                    ),
                    # Detalle del modelo
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [html.I(className="fa-solid fa-microchip me-2"), "Detalle del modelo"]
                                ),
                                dbc.CardBody(html.Div(id="detail-model")),
                            ],
                            class_name="h-100",
                        ),
                        xs=12, md=6, lg=3, class_name="mb-3",
                    ),
                    # Factores
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [html.I(className="fa-solid fa-list-check me-2"),
                                     "Factores influyentes"]
                                ),
                                dbc.CardBody(html.Div(id="detail-factors")),
                            ],
                            class_name="h-100",
                        ),
                        xs=12, md=6, lg=3, class_name="mb-3",
                    ),
                    # Backtest
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [html.I(className="fa-solid fa-chart-line me-2"), "Backtest"]
                                ),
                                dbc.CardBody(html.Div(id="detail-backtest")),
                            ],
                            class_name="h-100",
                        ),
                        xs=12, md=6, lg=3, class_name="mb-3",
                    ),
                ],
                id="detail-row",
            ),

            # ── Panel de ejecución manual ─────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader(
                        [html.I(className="fa-solid fa-bolt me-2"), "Ejecutar Orden Manual"]
                    ),
                    dbc.CardBody(
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Div(id="exec-symbol-info", className="d-flex align-items-center gap-3"),
                                    xs=12, md=5,
                                ),
                                dbc.Col(
                                    dbc.InputGroup(
                                        [
                                            dbc.InputGroupText("$"),
                                            dbc.Input(
                                                id="exec-amount",
                                                value="1000",
                                                type="number",
                                                min=10,
                                                size="sm",
                                                style={"maxWidth": "100px"},
                                            ),
                                            dbc.InputGroupText("importe"),
                                        ],
                                        size="sm",
                                    ),
                                    xs=12, md=3,
                                    class_name="d-flex align-items-center",
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        "Selecciona una señal",
                                        id="exec-order-btn",
                                        size="sm",
                                        disabled=True,
                                        color="secondary",
                                    ),
                                    xs=12, md="auto",
                                    class_name="d-flex align-items-center",
                                ),
                            ],
                            align="center",
                            class_name="g-2",
                        )
                    ),
                    html.Div(id="exec-order-result", className="px-3 pb-2"),
                ],
                id="exec-order-card",
                class_name="mb-3",
                style={"display": "none"},
            ),

            # Alerts
            html.Div(id="analisis-alert"),
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Callbacks
# ─────────────────────────────────────────────────────────────────────────────

@callback(
    Output("exec-amount-collapse", "is_open"),
    Input("analisis-auto-exec", "value"),
)
def toggle_exec_amount(checked):
    return bool(checked)


# ── Gestión de chips (multi-símbolo) ─────────────────────────────────────────

@callback(
    Output("analisis-symbols-store", "data"),
    Input("analisis-add-btn", "n_clicks"),
    Input({"type": "chip-close", "index": ALL}, "n_clicks"),
    State("analisis-combo", "value"),
    State("analisis-symbols-store", "data"),
    prevent_initial_call=True,
)
def manage_chips(add_clicks, close_clicks, selected_value, current_symbols):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_symbols

    trigger_id = ctx.triggered[0]["prop_id"]

    if "analisis-add-btn" in trigger_id:
        if not selected_value or selected_value == "__ALL__":
            return current_symbols
        if selected_value not in current_symbols:
            return current_symbols + [selected_value]
        return current_symbols

    # chip close button — ignorar disparos fantasma (n_clicks=0 al renderizar)
    if "chip-close" in trigger_id:
        if not ctx.triggered[0].get("value"):
            return dash.no_update
        import json as _json
        prop = ctx.triggered[0]["prop_id"]
        idx = _json.loads(prop.split(".")[0])["index"]
        return [s for s in current_symbols if s != idx]

    return current_symbols


@callback(
    Output("analisis-chips", "children"),
    Input("analisis-symbols-store", "data"),
    Input("analisis-combo", "value"),
)
def render_chips(symbols, combo_value):
    if not symbols:
        # Sin chips: mostrar lo que se analizará según el combo
        if combo_value == "__ALL__":
            label = "Todos (S&P100) — 100 símbolos"
        else:
            label = combo_value or "—"
        return html.Span(
            [
                html.I(className="fa-solid fa-circle-info me-1 text-info", style={"fontSize": "0.75rem"}),
                html.Span("Se analizará: ", className="text-muted", style={"fontSize": "0.8rem"}),
                html.Span(label, style={"fontSize": "0.8rem", "color": "#00bc8c", "fontWeight": "600"}),
                html.Span(" · Usa + Agregar para combinar varios", className="text-muted", style={"fontSize": "0.75rem"}),
            ]
        )

    # Con chips: mostrar badges con × para eliminar
    chips = []
    for sym in symbols:
        chips.append(
            dbc.Badge(
                [
                    sym,
                    html.Span(
                        " ×",
                        id={"type": "chip-close", "index": sym},
                        n_clicks=0,
                        style={"cursor": "pointer", "marginLeft": "4px", "fontWeight": "bold"},
                    ),
                ],
                color="primary",
                pill=True,
                class_name="me-1",
                style={"fontSize": "0.8rem", "padding": "5px 10px"},
            )
        )
    return chips


# ── Análisis ──────────────────────────────────────────────────────────────────

@callback(
    Output("analisis-grid",         "rowData"),
    Output("analisis-results-store","data"),
    Output("analisis-status",       "children"),
    Output("analisis-alert",        "children"),
    Input("analisis-run-btn",       "n_clicks"),
    State("analisis-symbols-store", "data"),
    State("analisis-combo",         "value"),
    State("analisis-desde",         "value"),
    State("analisis-hasta",         "value"),
    State("analisis-threshold",     "value"),
    prevent_initial_call=True,
)
def run_analysis(n_clicks, stored_symbols, combo_value, desde, hasta, threshold):
    if not n_clicks:
        return [], [], "", ""

    # Determinar símbolos
    if stored_symbols:
        symbols = stored_symbols
    elif combo_value == "__ALL__":
        symbols = list(SP100_SYMBOLS)
    elif combo_value:
        symbols = [combo_value]
    else:
        return [], [], "", dbc.Alert("Selecciona al menos un símbolo.", color="warning")

    # Parsear fechas (DD-MM-AAAA → YYYY-MM-DD)
    def parse_date(raw):
        from datetime import datetime
        if not raw or not raw.strip():
            return None
        try:
            return datetime.strptime(raw.strip(), "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError:
            return "2022-01-01"

    start_date = parse_date(desde) or "2022-01-01"
    end_date   = parse_date(hasta)
    try:
        thr = max(0.0, min(float(threshold or 0.5) / 100.0, 0.05))
    except (ValueError, TypeError):
        thr = 0.005

    try:
        from pathlib import Path
        from src.config.config_manager import ConfigManager
        from src.data.data_loader import DataLoader
        from src.analysis.trading_bot import TradingBot

        cfg = ConfigManager()
        api_key, secret_key = cfg.get_credentials()
        root = Path(__file__).resolve().parents[2]
        loader = DataLoader(api_key, secret_key, cache_dir=root / "data_cache")
        bot    = TradingBot(loader, model_dir=root / "models")
    except Exception as exc:
        return [], [], "", dbc.Alert(str(exc), color="danger")

    rows        = []
    full_data   = []
    errors      = []
    raw_results = []

    for sym in symbols:
        try:
            result = bot.run_symbol(
                sym,
                start_date=start_date,
                return_threshold=thr,
                progress=lambda msg: None,
            )
            raw_results.append(result)
            signal  = result.get("signal", "NEUTRAL")
            pred    = result.get("pred_return", 0) * 100
            metrics = result.get("metrics", {})
            quote   = result.get("quote", {})          # clave correcta
            price   = quote.get("ask_price", 0)
            da      = metrics.get("oos_dir_acc", 0)
            conf    = "Alta" if da >= 0.54 else "Media" if da >= 0.51 else "Baja"
            sign    = "+" if pred >= 0 else ""
            bt_metrics = result.get("backtest", {}).get("metrics", {})

            rows.append({
                "symbol":     sym,
                "signal":     signal,
                "pred_pct":   f"{sign}{pred:.2f}%",
                "price":      f"${price:,.2f}" if price else "—",
                "confidence": conf,
                "status":     "✓ OK",
            })
            # Solo guardamos datos JSON-serializables (sin DataFrames)
            importance_raw = result.get("importance", {})
            full_data.append({
                "symbol":      sym,
                "signal":      signal,
                "pred_return": float(result.get("pred_return", 0)),
                "metrics":     {k: float(v) for k, v in metrics.items()},
                "bt_metrics":  {k: float(v) for k, v in bt_metrics.items()},
                "quote":       {k: float(v) if isinstance(v, (int, float)) else v
                                for k, v in quote.items()},
                "importance":  {k: float(v) for k, v in importance_raw.items()},
                "sentiment":   result.get("sentiment", {}),
            })
        except Exception as exc:
            rows.append({
                "symbol":     sym,
                "signal":     "—",
                "pred_pct":   "—",
                "price":      "—",
                "confidence": "—",
                "status":     f"✗ {str(exc)[:40]}",
            })
            errors.append(sym)

    n_ok  = len(rows) - len(errors)
    n_err = len(errors)
    status_msg = f"Analizados {n_ok} símbolo(s) correctamente"
    if n_err:
        status_msg += f" · {n_err} error(es): {', '.join(errors)}"

    try:
        from src.analysis.scan_logger import append_scan_log
        append_scan_log(root, raw_results)
    except Exception:
        pass  # el registro histórico no debe romper el análisis en curso

    return rows, full_data, status_msg, ""


# ── Detalle al seleccionar fila ────────────────────────────────────────────────

@callback(
    Output("detail-signal",  "children"),
    Output("detail-model",   "children"),
    Output("detail-factors", "children"),
    Output("detail-backtest","children"),
    Input("analisis-grid",   "selectedRows"),
    State("analisis-results-store", "data"),
)
def update_detail(selected_rows, full_data):
    empty = html.Div("Selecciona una fila", className="text-muted text-center py-3")
    if not selected_rows or not full_data:
        return empty, empty, empty, empty

    sym    = selected_rows[0].get("symbol")
    result = next((r for r in full_data if r.get("symbol") == sym), None)
    if not result:
        return empty, empty, empty, empty

    signal  = result.get("signal", "—")
    pred    = result.get("pred_return", 0) * 100
    metrics = result.get("metrics", {})
    bt      = result.get("bt_metrics", {})
    quote   = result.get("quote", {})

    sig_color = (
        "#00bc8c" if "COMPRAR" in signal and "débil" not in signal
        else "#e74c3c" if "VENDER" in signal and "débil" not in signal
        else "#f39c12" if "débil" in signal or "debil" in signal
        else "#888"
    )
    sign = "+" if pred >= 0 else ""

    # Card 1: Señal
    ask  = quote.get("ask_price", 0)
    bid  = quote.get("bid_price", 0)
    sent = result.get("sentiment", {}).get("sentiment_score", None)
    signal_content = [
        html.Div(signal, className="kpi-value mb-2", style={"color": sig_color, "fontSize": "1.4rem"}),
        html.Div(f"Retorno predicho: {sign}{pred:.2f}%", className="mb-1"),
        html.Div(f"Ask: ${ask:,.2f} · Bid: ${bid:,.2f}", className="scan-timestamp"),
        html.Div(f"Sentiment: {sent:+.3f}" if sent is not None else "", className="scan-timestamp mt-1"),
    ]

    # Card 2: Modelo
    da         = metrics.get("oos_dir_acc", 0)
    conf       = "Alta" if da >= 0.54 else "Media" if da >= 0.51 else "Baja"
    conf_color = "#00bc8c" if da >= 0.54 else "#f39c12" if da >= 0.51 else "#e74c3c"
    model_content = [
        html.Div(
            [html.Span("Confianza: "), html.Span(conf, style={"color": conf_color, "fontWeight": "700"})],
            className="fw-bold mb-2",
        ),
        html.Div(f"Precisión direccional: {da*100:.1f}%", className="mb-1"),
        html.Div(
            ["OOS MAE: ", f"{metrics.get('oos_mae', 0)*100:.2f}%", _info_icon("oos-mae-tt", OOS_MAE_TOOLTIP)],
            className="scan-timestamp",
        ),
        html.Div(f"Muestras: {metrics.get('n_samples', '—'):,}", className="scan-timestamp mt-1"),
    ]

    # Card 3: Factores
    importances = result.get("importance", {})
    if importances:
        top     = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:6]
        max_val = top[0][1] if top else 1
        factors_content = html.Div([
            html.Div([
                html.Span(
                    [feat, _info_icon(f"feat-tt-{feat}", FEATURE_TOOLTIPS.get(feat, feat))],
                    className="me-2", style={"fontSize": "0.78rem"},
                ),
                dbc.Progress(value=round(val / max_val * 100), color="success",
                             style={"height": "5px"}, class_name="mt-1"),
            ], className="mb-2")
            for feat, val in top
        ])
    else:
        factors_content = html.Div("Sin datos de importancia", className="text-muted")

    # Card 4: Backtest
    n_trades = bt.get("n_trades", 0)
    backtest_content = [
        _bt_row("Trades",      str(n_trades)),
        _bt_row("Win rate",    f"{bt.get('win_rate', 0)*100:.1f}%",    tip=BACKTEST_TOOLTIPS["Win rate"]),
        _bt_row("Sharpe",      f"{bt.get('sharpe', 0):.2f}",           tip=BACKTEST_TOOLTIPS["Sharpe"]),
        _bt_row("Max DD",      f"{bt.get('max_drawdown', 0)*100:.1f}%", "#e74c3c", tip=BACKTEST_TOOLTIPS["Max DD"]),
        _bt_row("CAGR",        f"{bt.get('cagr', 0)*100:.1f}%",        tip=BACKTEST_TOOLTIPS["CAGR"]),
        _bt_row("Alpha",       f"{bt.get('alpha', 0):.2f}%",           tip=BACKTEST_TOOLTIPS["Alpha"]),
        _bt_row("B&H return",  f"{bt.get('bh_return', 0):.1f}%",       tip=BACKTEST_TOOLTIPS["B&H return"]),
    ] if n_trades else [html.Div("Sin trades en el backtest", className="text-muted")]

    return signal_content, model_content, factors_content, backtest_content


# ── Panel ejecución manual: poblar al seleccionar fila ───────────────────────

@callback(
    Output("exec-order-card",   "style"),
    Output("exec-symbol-info",  "children"),
    Output("exec-order-btn",    "children"),
    Output("exec-order-btn",    "color"),
    Output("exec-order-btn",    "disabled"),
    Output("exec-order-result", "children"),
    Input("analisis-grid",      "selectedRows"),
    State("analisis-results-store", "data"),
)
def populate_exec_panel(selected_rows, full_data):
    hidden = {"display": "none"}
    visible = {"display": "block"}
    empty = (hidden, [], "—", "secondary", True, "")

    if not selected_rows or not full_data:
        return empty

    sym    = selected_rows[0].get("symbol", "")
    result = next((r for r in full_data if r.get("symbol") == sym), None)
    if not result:
        return empty

    signal = result.get("signal", "NEUTRAL")
    pred   = result.get("pred_return", 0) * 100
    quote  = result.get("quote", {})
    price  = quote.get("ask_price", 0) or quote.get("bid_price", 0)

    if "COMPRAR" in signal:
        btn_label = [html.I(className="fa-solid fa-arrow-trend-up me-2"), f"Comprar {sym}"]
        btn_color = "success"
    elif "VENDER" in signal:
        btn_label = [html.I(className="fa-solid fa-arrow-trend-down me-2"), f"Vender {sym}"]
        btn_color = "danger"
    else:
        return empty  # NEUTRAL: no mostramos panel

    sign = "+" if pred >= 0 else ""
    sig_color = "#00bc8c" if "COMPRAR" in signal else "#e74c3c"
    if "débil" in signal:
        sig_color = "#f39c12"

    info = [
        html.Span(sym, style={"fontWeight": "700", "fontSize": "1.1rem"}),
        html.Span(signal, style={"color": sig_color, "fontWeight": "600"}),
        html.Span(f"Ret. predicho: {sign}{pred:.2f}%", className="text-muted", style={"fontSize": "0.85rem"}),
        html.Span(f"Precio: ${price:,.2f}" if price else "", className="text-muted", style={"fontSize": "0.85rem"}),
    ]

    return visible, info, btn_label, btn_color, False, ""


# ── Ejecutar orden manual ─────────────────────────────────────────────────────

@callback(
    Output("exec-order-result", "children", allow_duplicate=True),
    Input("exec-order-btn",     "n_clicks"),
    State("analisis-grid",      "selectedRows"),
    State("analisis-results-store", "data"),
    State("exec-amount",        "value"),
    prevent_initial_call=True,
)
def execute_manual_order(n_clicks, selected_rows, full_data, amount):
    if not n_clicks or not selected_rows or not full_data:
        return ""

    sym    = selected_rows[0].get("symbol", "")
    result = next((r for r in full_data if r.get("symbol") == sym), None)
    if not result:
        return dbc.Alert("No hay datos para este símbolo.", color="warning")

    try:
        trade_amount = float(amount or 1000)
    except (ValueError, TypeError):
        trade_amount = 1000.0

    try:
        from src.config.config_manager import ConfigManager
        from src.trading.order_executor import OrderExecutor

        cfg              = ConfigManager()
        api_key, sec_key = cfg.get_credentials()
        executor         = OrderExecutor(api_key, sec_key)

        exec_result = executor.execute_signal(
            symbol           = sym,
            signal           = result.get("signal", ""),
            pred_return      = result.get("pred_return", 0),
            quote            = result.get("quote", {}),
            metrics          = result.get("metrics", {}),
            trade_amount     = trade_amount,
            backtest_metrics = result.get("bt_metrics", {}),
        )

        action = exec_result.get("action", "skip")
        reason = exec_result.get("reason", "")
        order  = exec_result.get("order")

        if action in ("buy", "sell") and order:
            side  = "Compra" if action == "buy" else "Venta"
            color = "success" if action == "buy" else "danger"
            return dbc.Alert(
                [
                    html.I(className="fa-solid fa-check-circle me-2"),
                    html.Strong(f"{side} ejecutada — {sym}: "),
                    f"{order.get('qty', '?')} acciones @ ${order.get('limit_price', '?'):.2f} "
                    f"· Estado: {order.get('status', '?')}",
                ],
                color=color, dismissable=True,
            )
        elif action == "skip":
            return dbc.Alert(
                [html.I(className="fa-solid fa-info-circle me-2"), f"Orden omitida: {reason}"],
                color="warning", dismissable=True,
            )
        else:
            return dbc.Alert(f"Error: {reason}", color="danger", dismissable=True)

    except Exception as exc:
        return dbc.Alert(str(exc), color="danger", dismissable=True)


# ── Actualizar resultados reales ──────────────────────────────────────────────

@callback(
    Output("analisis-alert", "children", allow_duplicate=True),
    Input("analisis-update-btn", "n_clicks"),
    prevent_initial_call=True,
)
def update_actuals(n_clicks):
    if not n_clicks:
        return ""
    try:
        from pathlib import Path
        from src.analysis.prediction_tracker import update_actuals as _update

        base_dir = Path(__file__).resolve().parents[2] / "Analisis_Predicción"
        _update(base_dir)
        return dbc.Alert(
            [html.I(className="fa-solid fa-check-circle me-2"), "Resultados reales actualizados correctamente."],
            color="success", dismissable=True,
        )
    except Exception as exc:
        return dbc.Alert(str(exc), color="danger", dismissable=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bt_row(label: str, value: str, color: str = "#c0c0e0", tip: str | None = None):
    label_children = [label]
    if tip:
        label_children.append(_info_icon(f"bt-tt-{label}", tip))
    return dbc.Row(
        [
            dbc.Col(html.Span(label_children, className="text-muted"), width=7, style={"fontSize": "0.8rem"}),
            dbc.Col(html.Span(value, style={"color": color, "fontWeight": "600", "fontSize": "0.8rem"}), width=5, class_name="text-end"),
        ],
        class_name="mb-1",
    )
