# -*- coding: utf-8 -*-
import json
from pathlib import Path

import dash
from dash import html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

dash.register_page(
    __name__,
    path="/configuracion",
    name="Configuración",
    title="AlgoTrader · Configuración",
)

from src.analysis.strategies import BY_ID, ESTADO_COLOR, STRATEGIES, can_trade, status  # noqa: E402
from src.config.settings_manager import settings, DATA_SOURCES, INFO_SOURCES, MODEL_TYPES  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

_CARD_STYLE = {"border": "1px solid #222", "background": "#111"}

_MODEL_OPTIONS = [{"label": v, "value": k} for k, v in MODEL_TYPES.items()]

_SOURCE_LABELS = {
    "yahoo":         "Yahoo Finance",
    "alpaca":        "Alpaca Markets",
    "alpha_vantage": "Alpha Vantage",
    "polygon":       "Polygon.io",
}

_ROL_COLOR = {"Principal": "success", "Activa": "info", "Respaldo": "secondary", "Pendiente": "warning"}


def _header(icon: str, text: str):
    return dbc.CardHeader(html.Div([
        html.I(className=f"fa-solid {icon} me-2", style={"color": "#00bc8c"}), text,
    ], style={"fontWeight": "600", "fontSize": "0.9rem"}))


def _strategy_options():
    opts = []
    for s in STRATEGIES:
        est = status(s.id)
        badges = [dbc.Badge(est, color=ESTADO_COLOR[est], className="ms-2", style={"fontSize": "0.68rem"})]
        if s.recomendada and est != "Descartada":
            badges.insert(0, dbc.Badge("Recomendada", color="success", className="ms-2",
                                       style={"fontSize": "0.68rem"}))
        prio = f"Prioridad {s.prioridad}" if s.prioridad < 9 else "Referencia"
        opts.append({
            "label": html.Span([
                html.Strong(s.nombre), *badges, html.Br(),
                html.Small(f"{prio} · {s.fuente}", style={"color": "#888"}),
            ]),
            "value": s.id,
            "disabled": not s.datos_listos,
        })
    return opts


def _count(path: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in path.glob(pattern))
    except Exception:
        return 0


def _info_source_status(key: str) -> str:
    """Estado de los datos descargados de cada fuente de información."""
    if key == "sec_companyfacts":
        n = _count(ROOT / "data_cache" / "sec", "*.json") - (1 if (ROOT / "data_cache" / "sec" / "company_tickers.json").exists() else 0)
        snap = _count(ROOT / "backtest_data" / "v2_sp500" / "sec", "*.json")
        return f"En caché: {max(n, 0)} empresas · snapshot backtest: {snap}"
    if key == "yahoo_earnings":
        n = _count(ROOT / "data_cache" / "earnings", "*.parquet")
        snap = _count(ROOT / "backtest_data" / "v2_sp500" / "earnings", "*.parquet")
        return f"En caché: {n} empresas · snapshot backtest: {snap}"
    if key == "av_earnings":
        return "Clave en .env (ALPHA_VANTAGE_API_KEY)"
    return "Descargador aún no implementado"


def _snapshot_status():
    m = ROOT / "backtest_data" / "v2_sp500" / "manifest.json"
    if m.exists():
        try:
            man = json.loads(m.read_text(encoding="utf-8"))
            ok = len({k.split("/")[1] for k in man["files"] if k.startswith("prices/")})
            return [html.I(className="fa-solid fa-lock me-1", style={"color": "#00bc8c"}),
                    f"Snapshot S&P 500 congelado el {man['created'][:10]}: {ok} empresas, "
                    f"{len(man.get('failed', {}))} sin datos."]
        except Exception:
            pass
    n = _count(ROOT / "backtest_data" / "v2_sp500" / "prices", "*.parquet")
    return [html.I(className="fa-solid fa-hourglass-half me-1", style={"color": "#f39c12"}),
            f"Snapshot S&P 500 en preparación ({n}/503 empresas descargadas)."]


def layout():
    cfg = settings.load()
    current_strategy = cfg["strategy"] if cfg["strategy"] in BY_ID else "h1_quality_value"

    info_rows = [
        html.Tr([
            html.Td([html.Strong(v["nombre"]), html.Br(),
                     html.Small(v["uso"], style={"color": "#888"})]),
            html.Td(v["coste"], style={"fontSize": "0.78rem", "color": "#aaa"}),
            html.Td(dbc.Badge(v["rol"], color=_ROL_COLOR[v["rol"]])),
            html.Td(_info_source_status(k), style={"fontSize": "0.75rem", "color": "#888"}),
        ])
        for k, v in INFO_SOURCES.items()
    ]

    return html.Div([
        html.H4("Configuración", className="page-title"),
        html.Div("Ajustes del sistema — se guardan en settings.json al pulsar Guardar",
                 className="page-subtitle"),

        # ── Estrategia principal ───────────────────────────────────────────
        dbc.Card([
            _header("fa-chess-knight", "Estrategia principal"),
            dbc.CardBody([
                dbc.RadioItems(
                    id="cfg-strategy",
                    options=_strategy_options(),
                    value=current_strategy,
                    labelStyle={"display": "flex", "alignItems": "flex-start",
                                "marginBottom": "12px", "gap": "8px"},
                    inputStyle={"marginTop": "4px"},
                ),
                html.Div(id="cfg-strategy-info"),
                dcc.Link("Ver detalle y resultados en Estrategias →", href="/estrategias",
                         style={"fontSize": "0.82rem"}),
            ]),
        ], style=_CARD_STYLE, className="mb-3"),

        # ── Fuentes de información (no precio) ────────────────────────────
        dbc.Card([
            _header("fa-file-invoice-dollar", "Fuentes de información (además del precio)"),
            dbc.CardBody([
                html.Div(dbc.Table(
                    [html.Thead(html.Tr([html.Th("Fuente"), html.Th("Coste / límite"),
                                         html.Th("Rol"), html.Th("Datos")])),
                     html.Tbody(info_rows)],
                    size="sm", borderless=True, className="cfg-table mb-2", color="dark",
                ), style={"overflowX": "auto"}),
                html.Div(_snapshot_status(), style={"fontSize": "0.8rem", "color": "#aaa"}),
                html.Div("Universo: S&P 500 actual (503 empresas). Ojo: no incluye las que salieron "
                         "del índice → los backtests son algo optimistas.",
                         style={"fontSize": "0.78rem", "color": "#888", "marginTop": "6px"}),
            ]),
        ], style=_CARD_STYLE, className="mb-3"),

        dbc.Row([
            # ── Fuente de precios ─────────────────────────────────────────
            dbc.Col([
                dbc.Card([
                    _header("fa-database", "Fuente de precios (velas diarias)"),
                    dbc.CardBody([
                        dbc.RadioItems(
                            id="cfg-source",
                            options=[
                                {"label": html.Span([
                                    html.Strong(_SOURCE_LABELS[k]),
                                    html.Span(f"  —  {v}", style={"color": "#888", "fontSize": "0.8rem"}),
                                ]), "value": k}
                                for k, v in DATA_SOURCES.items()
                            ],
                            value=cfg["data_source"],
                            labelStyle={"display": "flex", "alignItems": "flex-start",
                                        "marginBottom": "10px", "gap": "8px"},
                            inputStyle={"marginTop": "3px"},
                        ),
                        html.Hr(style={"borderColor": "#222"}),
                        html.Div(id="cfg-source-info", style={"fontSize": "0.82rem", "color": "#aaa"}),
                    ]),
                ], style=_CARD_STYLE),
            ], md=6),

            # ── Modelo ML + modo de escaneo ───────────────────────────────
            dbc.Col([
                dbc.Card([
                    _header("fa-brain", "Modelo ML (solo estrategia «ML diario»)"),
                    dbc.CardBody([
                        dcc.Dropdown(id="cfg-model", options=_MODEL_OPTIONS, value=cfg["model_type"],
                                     clearable=False, className="cfg-dropdown",
                                     style={"backgroundColor": "#0d0d14", "color": "#c0c0e0",
                                            "border": "1px solid #2a2a3a"}),
                        html.Div(id="cfg-model-info", style={"fontSize": "0.82rem", "color": "#aaa",
                                                             "marginTop": "10px"}),
                    ]),
                ], style=_CARD_STYLE, className="mb-3"),

                dbc.Card([
                    _header("fa-robot", "Modo del scan diario (ML diario, S&P 100)"),
                    dbc.CardBody([
                        dbc.RadioItems(
                            id="cfg-mode",
                            options=[
                                {"label": html.Span([html.Strong("Automático"), html.Span(
                                    "  —  Cada día a las 14:45 (lunes a viernes).",
                                    style={"color": "#888", "fontSize": "0.8rem"})]), "value": "auto"},
                                {"label": html.Span([html.Strong("Manual"), html.Span(
                                    "  —  Solo cuando pulsas el botón en Inicio.",
                                    style={"color": "#888", "fontSize": "0.8rem"})]), "value": "manual"},
                            ],
                            value=cfg["scan_mode"],
                            labelStyle={"display": "flex", "alignItems": "flex-start",
                                        "marginBottom": "10px", "gap": "8px"},
                            inputStyle={"marginTop": "3px"},
                        ),
                    ]),
                ], style=_CARD_STYLE),
            ], md=6),
        ], className="mb-3 g-3"),

        dbc.Row([dbc.Col([
            dbc.Button([html.I(className="fa-solid fa-floppy-disk me-2"), "Guardar configuración"],
                       id="cfg-save-btn", color="success", class_name="me-2"),
            html.Span(id="cfg-save-status", style={"fontSize": "0.85rem", "color": "#888"}),
        ])]),

        dbc.Toast("Configuración guardada correctamente.", id="cfg-toast", header="Guardado",
                  is_open=False, dismissable=True, icon="success", duration=3000,
                  style={"position": "fixed", "bottom": "20px", "right": "20px", "zIndex": 9999}),
    ])


# ── Callbacks ────────────────────────────────────────────────────────────────

@callback(Output("cfg-strategy-info", "children"), Input("cfg-strategy", "value"))
def update_strategy_info(strategy_id):
    s = BY_ID.get(strategy_id or "h1_quality_value")
    if s is None:
        return ""
    est = status(s.id)
    if can_trade(s.id):
        aviso = dbc.Alert([html.I(className="fa-solid fa-circle-check me-2"),
                           "Aprobada en el backtest fijo: puede enviar órdenes."],
                          color="success", className="py-2 mb-2")
    else:
        aviso = dbc.Alert([html.I(className="fa-solid fa-shield-halved me-2"),
                           f"Estado: {est}. ", html.Strong("No enviará órdenes"),
                           " hasta que esté Aprobada en el backtest fijo. Mientras tanto verás su "
                           "cartera teórica en Estrategias."],
                          color="warning", className="py-2 mb-2")
    return html.Div([
        html.P(s.resumen, style={"fontSize": "0.82rem", "color": "#aaa", "marginBottom": "6px"}),
        aviso,
    ], style={"fontSize": "0.82rem"})


@callback(Output("cfg-source-info", "children"), Input("cfg-source", "value"))
def update_source_info(source):
    info_map = {
        "yahoo": [html.I(className="fa-solid fa-circle-check me-1", style={"color": "#00bc8c"}),
                  "Recomendada: es la fuente del backtest fijo (precios ajustados desde 2010). "
                  "No oficial: Yahoo puede fallar puntualmente."],
        "alpaca": [html.I(className="fa-solid fa-circle-info me-1", style={"color": "#3ea6ff"}),
                   "Oficial y estable, pero el feed gratuito (IEX) solo tiene histórico desde el "
                   "27-07-2020: los modelos entrenan con ~6 años. Precios ajustados por splits."],
        "alpha_vantage": [html.I(className="fa-solid fa-triangle-exclamation me-1", style={"color": "#f39c12"}),
                          "Con la clave gratuita los precios diarios ajustados NO están disponibles "
                          "(verificado el 14-10-2026). Solo sirve con plan de pago."],
        "polygon": [html.I(className="fa-solid fa-triangle-exclamation me-1", style={"color": "#e74c3c"}),
                    "Añade POLYGON_API_KEY en .env. Requiere suscripción activa en polygon.io."],
    }
    return html.Div(info_map.get(source or "yahoo", []))


@callback(Output("cfg-model-info", "children"), Input("cfg-model", "value"))
def update_model_info(model):
    info_map = {
        "xgb_lgb_ensemble":  "Combina XGBoost y LightGBM.",
        "xgboost":           "XGBoost solo.",
        "lightgbm":          "LightGBM solo. Muy rápido.",
        "random_forest":     "Random Forest. Es el medido en el backtest fijo (sin ventaja).",
        "ridge":             "Modelo lineal. Útil como referencia.",
        "gradient_boosting": "Gradient Boosting de sklearn.",
        "xgb_rf_ensemble":   "Combina XGBoost y Random Forest.",
    }
    return [info_map.get(model or "xgb_lgb_ensemble", ""), html.Br(),
            html.Span("Solo afecta a la pestaña Análisis y al scan diario del S&P 100.",
                      style={"color": "#777"})]


@callback(
    Output("cfg-toast", "is_open"),
    Output("cfg-save-status", "children"),
    Input("cfg-save-btn", "n_clicks"),
    State("cfg-strategy", "value"),
    State("cfg-source", "value"),
    State("cfg-model", "value"),
    State("cfg-mode", "value"),
    prevent_initial_call=True,
)
def save_settings(n_clicks, strategy, source, model, mode):
    if not n_clicks:
        return False, ""
    settings.save({"strategy": strategy, "data_source": source, "model_type": model, "scan_mode": mode})
    return True, ""
