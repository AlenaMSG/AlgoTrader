# -*- coding: utf-8 -*-
import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

dash.register_page(
    __name__,
    path="/configuracion",
    name="Configuración",
    title="AlgoTrader · Configuración",
)

from src.config.settings_manager import settings, DATA_SOURCES, MODEL_TYPES  # noqa: E402

# ── Opciones para los controles ─────────────────────────────────────────────

_SOURCE_OPTIONS = [
    {
        "label": html.Span(
            [html.Strong(k.replace("_", " ").title()), html.Br(),
             html.Small(v, style={"color": "#888", "fontWeight": "400"})],
        ),
        "value": k,
    }
    for k, v in DATA_SOURCES.items()
]

_MODEL_OPTIONS = [
    {"label": v, "value": k}
    for k, v in MODEL_TYPES.items()
]

_SOURCE_LABELS = {
    "yahoo":         "Yahoo Finance",
    "alpaca":        "Alpaca Markets",
    "alpha_vantage": "Alpha Vantage",
    "polygon":       "Polygon.io",
}

_SOURCE_DESCRIPTIONS = {
    "yahoo": [
        html.Li("Gratis, sin registro ni API key."),
        html.Li("Histórico desde los años 90."),
        html.Li(["No es oficial — Yahoo puede interrumpirlo sin avisar.",
                 html.Br(), "Algunos tickers pueden fallar ocasionalmente."]),
    ],
    "alpaca": [
        html.Li("Ya tienes las credenciales configuradas en .env."),
        html.Li("API oficial y estable."),
        html.Li("Plan gratuito: hasta ~5 años de histórico diario."),
        html.Li("Para más histórico necesitas el plan de pago."),
    ],
    "alpha_vantage": [
        html.Li("Requiere API key (registro gratuito en alphavantage.co)."),
        html.Li("Plan gratuito: solo 25 llamadas/día — insuficiente para el scan completo del S&P 100."),
        html.Li("Con plan de pago (desde 50 $/mes): sin límite práctico."),
        html.Li("Histórico completo y muy fiable."),
    ],
    "polygon": [
        html.Li("Servicio de pago (desde 29 $/mes)."),
        html.Li("El más fiable y rápido del mercado."),
        html.Li("Histórico completo + datos en tiempo real."),
        html.Li("Requiere API key y suscripción activa."),
    ],
}

_SOURCE_BADGE = {
    "yahoo":         ("Recomendado para empezar", "success"),
    "alpaca":        ("Ya configurado", "info"),
    "alpha_vantage": ("Plan de pago recomendado", "warning"),
    "polygon":       ("De pago", "danger"),
}


def _source_card(source_id: str, selected: str):
    label = _SOURCE_LABELS[source_id]
    badge_text, badge_color = _SOURCE_BADGE[source_id]
    is_selected = source_id == selected
    border = "2px solid #00bc8c" if is_selected else "1px solid #222"
    bg = "#0a1a12" if is_selected else "#111"

    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col(
                    dbc.RadioItems(
                        id={"type": "source-radio", "index": source_id},
                        options=[{"label": "", "value": source_id}],
                        value=source_id if is_selected else None,
                        inline=True,
                        style={"marginTop": "2px"},
                    ),
                    width="auto",
                ),
                dbc.Col([
                    html.Div([
                        html.Strong(label, style={"fontSize": "0.95rem"}),
                        dbc.Badge(badge_text, color=badge_color,
                                  className="ms-2", style={"fontSize": "0.7rem"}),
                    ]),
                    html.Ul(
                        _SOURCE_DESCRIPTIONS[source_id],
                        style={"fontSize": "0.82rem", "color": "#aaa",
                               "marginTop": "6px", "marginBottom": "0",
                               "paddingLeft": "1.1rem"},
                    ),
                ]),
            ], align="start"),
        ]),
        style={"border": border, "background": bg, "cursor": "pointer",
               "transition": "border 0.15s, background 0.15s"},
        class_name="mb-2",
        id={"type": "source-card", "index": source_id},
    )


def layout():
    cfg = settings.load()
    current_source = cfg["data_source"]
    current_model  = cfg["model_type"]
    current_mode   = cfg["scan_mode"]

    return html.Div([
        dcc.Store(id="cfg-saved-store", data=False),

        html.H4("Configuración", className="page-title"),
        html.Div("Ajustes del sistema — se guardan automáticamente en settings.json",
                 className="page-subtitle"),

        dbc.Row([
            # ── Columna izquierda: Fuente de datos ─────────────────────────
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(
                        html.Div([
                            html.I(className="fa-solid fa-database me-2",
                                   style={"color": "#00bc8c"}),
                            "Fuente de datos históricos",
                        ], style={"fontWeight": "600", "fontSize": "0.9rem"}),
                    ),
                    dbc.CardBody([
                        dbc.RadioItems(
                            id="cfg-source",
                            options=[
                                {"label": html.Span([
                                    html.Strong(_SOURCE_LABELS[k]),
                                    html.Span(
                                        f"  —  {v}",
                                        style={"color": "#888", "fontSize": "0.8rem"},
                                    ),
                                ]), "value": k}
                                for k, v in DATA_SOURCES.items()
                            ],
                            value=current_source,
                            labelStyle={"display": "flex", "alignItems": "flex-start",
                                        "marginBottom": "10px", "gap": "8px"},
                            inputStyle={"marginTop": "3px"},
                        ),
                        html.Hr(style={"borderColor": "#222"}),
                        html.Div(id="cfg-source-info",
                                 style={"fontSize": "0.82rem", "color": "#aaa"}),
                    ]),
                ], style={"border": "1px solid #222", "background": "#111"}),
            ], md=6),

            # ── Columna derecha: Modelo + Modo ─────────────────────────────
            dbc.Col([
                # Modelo ML
                dbc.Card([
                    dbc.CardHeader(
                        html.Div([
                            html.I(className="fa-solid fa-brain me-2",
                                   style={"color": "#00bc8c"}),
                            "Modelo de machine learning",
                        ], style={"fontWeight": "600", "fontSize": "0.9rem"}),
                    ),
                    dbc.CardBody([
                        dcc.Dropdown(
                            id="cfg-model",
                            options=_MODEL_OPTIONS,
                            value=current_model,
                            clearable=False,
                            style={
                                "backgroundColor": "#0d0d14",
                                "color": "#c0c0e0",
                                "border": "1px solid #2a2a3a",
                            },
                            className="cfg-dropdown",
                        ),
                        html.Div(id="cfg-model-info",
                                 style={"fontSize": "0.82rem", "color": "#aaa",
                                        "marginTop": "10px"}),
                    ]),
                ], style={"border": "1px solid #222", "background": "#111"},
                   className="mb-3"),

                # Modo de escaneo
                dbc.Card([
                    dbc.CardHeader(
                        html.Div([
                            html.I(className="fa-solid fa-robot me-2",
                                   style={"color": "#00bc8c"}),
                            "Modo de escaneo del S&P 100",
                        ], style={"fontWeight": "600", "fontSize": "0.9rem"}),
                    ),
                    dbc.CardBody([
                        dbc.RadioItems(
                            id="cfg-mode",
                            options=[
                                {
                                    "label": html.Span([
                                        html.Strong("Automático"),
                                        html.Span(
                                            "  —  El scan se ejecuta cada día a las 14:45 (lunes a viernes) sin intervención.",
                                            style={"color": "#888", "fontSize": "0.8rem"},
                                        ),
                                    ]),
                                    "value": "auto",
                                },
                                {
                                    "label": html.Span([
                                        html.Strong("Manual"),
                                        html.Span(
                                            "  —  El scan solo se ejecuta cuando pulsas el botón en la pestaña Análisis.",
                                            style={"color": "#888", "fontSize": "0.8rem"},
                                        ),
                                    ]),
                                    "value": "manual",
                                },
                            ],
                            value=current_mode,
                            labelStyle={"display": "flex", "alignItems": "flex-start",
                                        "marginBottom": "10px", "gap": "8px"},
                            inputStyle={"marginTop": "3px"},
                        ),
                    ]),
                ], style={"border": "1px solid #222", "background": "#111"}),
            ], md=6),
        ], className="mb-3 g-3"),

        # ── Botón guardar + toast confirmación ──────────────────────────────
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    [html.I(className="fa-solid fa-floppy-disk me-2"), "Guardar configuración"],
                    id="cfg-save-btn",
                    color="success",
                    class_name="me-2",
                ),
                html.Span(id="cfg-save-status", style={"fontSize": "0.85rem", "color": "#888"}),
            ]),
        ]),

        dbc.Toast(
            "Configuración guardada correctamente.",
            id="cfg-toast",
            header="Guardado",
            is_open=False,
            dismissable=True,
            icon="success",
            duration=3000,
            style={"position": "fixed", "bottom": "20px", "right": "20px", "zIndex": 9999},
        ),
    ])


# ── Callbacks ────────────────────────────────────────────────────────────────

@callback(
    Output("cfg-source-info", "children"),
    Input("cfg-source", "value"),
)
def update_source_info(source):
    info_map = {
        "yahoo": [
            html.I(className="fa-solid fa-circle-check me-1", style={"color": "#00bc8c"}),
            "Fuente actual del sistema. No requiere ninguna configuración adicional.",
        ],
        "alpaca": [
            html.I(className="fa-solid fa-circle-info me-1", style={"color": "#3ea6ff"}),
            "Asegúrate de tener ALPACA_API_KEY y ALPACA_SECRET_KEY en el fichero .env.",
        ],
        "alpha_vantage": [
            html.I(className="fa-solid fa-triangle-exclamation me-1", style={"color": "#f39c12"}),
            html.Span([
                "Añade ALPHA_VANTAGE_API_KEY en .env. Con el plan gratuito (25 req/día) "
                "no es posible escanear los 100 tickers del S&P. Se recomienda el plan de pago.",
            ]),
        ],
        "polygon": [
            html.I(className="fa-solid fa-triangle-exclamation me-1", style={"color": "#e74c3c"}),
            "Añade POLYGON_API_KEY en .env. Requiere suscripción activa en polygon.io.",
        ],
    }
    return html.Div(info_map.get(source or "yahoo", []))


@callback(
    Output("cfg-model-info", "children"),
    Input("cfg-model", "value"),
)
def update_model_info(model):
    info_map = {
        "xgb_lgb_ensemble":  "Combina XGBoost y LightGBM. Mayor precisión, más lento para entrenar.",
        "xgboost":           "XGBoost solo. Buen equilibrio velocidad/precisión.",
        "lightgbm":          "LightGBM solo. Muy rápido, especialmente en datasets grandes.",
        "random_forest":     "Robusto ante ruido. Menos preciso pero muy estable.",
        "ridge":             "Modelo lineal. El más rápido, útil como baseline.",
        "gradient_boosting": "Gradient Boosting de sklearn. Similar a XGBoost pero más lento.",
        "xgb_rf_ensemble":   "Combina XGBoost y Random Forest. Alternativa al ensemble por defecto.",
    }
    return info_map.get(model or "xgb_lgb_ensemble", "")


@callback(
    Output("cfg-toast", "is_open"),
    Output("cfg-save-status", "children"),
    Input("cfg-save-btn", "n_clicks"),
    State("cfg-source", "value"),
    State("cfg-model", "value"),
    State("cfg-mode", "value"),
    prevent_initial_call=True,
)
def save_settings(n_clicks, source, model, mode):
    if not n_clicks:
        return False, ""
    settings.save({"data_source": source, "model_type": model, "scan_mode": mode})
    return True, ""
