# -*- coding: utf-8 -*-
"""
Estrategias: las hipótesis H1–H3 por prioridad, su estado en el backtest fijo,
la cartera teórica de hoy de la estrategia principal y el historial de backtests.
"""
import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, dcc, html

dash.register_page(__name__, path="/estrategias", name="Estrategias",
                   title="AlgoTrader · Estrategias")

from src.analysis.strategies import (ESTADO_COLOR, HISTORIAL, MAX_INTENTOS, STRATEGIES,  # noqa: E402
                                     BY_ID, attempts, results, status)
from src.config.settings_manager import settings  # noqa: E402
from web import strategy_runner  # noqa: E402

CARTERA_DISPONIBLE = {"h1_quality_value", "h2_earnings_surprise", "h3_insider_buying"}

# Nombre legible de cada fila del historial (columna `variant` de historial.csv)
NOMBRES_HIST = {
    "base": "Modelo ML diario (anterior)",
    "earnings_skip_3": "ML diario + filtro de resultados",
    "momentum": "E1 · Momentum 12-1",
    "reversal": "E2 · Reversión 5 días",
    "ml20": "E3 · ML a 20 días",
    "h1_quality_value_v2": "H1 · Calidad + valor",
    "h2_earnings_surprise_v2": "H2 · Sorpresa en resultados",
    "h3_insider_buying_v2": "H3 · Compras de directivos",
}

_HELP_ESTADOS = [
    ("En validación", "Aún no se ha medido en el backtest."),
    ("No aceptada", "Se midió y no cumple los 3 criterios, pero le quedan intentos (máx. 3). "
                    "Cada intento nuevo exige escribir antes el porqué del cambio."),
    ("Descartada", "Agotó sus intentos o se cerró: no se vuelve a probar."),
    ("Pendiente holdout", "Cumple en 2016-2025; falta la prueba única con el último año, que nunca se ha mirado."),
    ("Aprobada", "Cumple también en el holdout. Solo entonces puede enviar órdenes."),
    ("Sin datos", "Falta descargar y congelar su fuente de datos."),
]

_HELP_METRICAS = [
    ("Rentab. anual", "Lo que habría ganado de media cada año, ya descontadas comisiones. "
                      "«bench» es lo mismo para el índice: comprar todas las acciones a partes iguales."),
    ("Sharpe", "Rentabilidad por unidad de riesgo (cuánto se mueve). Criterio 1: ha de ser mayor que el del "
               "índice; ganar más pero con mucho más riesgo no cuenta."),
    ("IC (t)", "Si la puntuación ordena bien las acciones (las de arriba suben más que las de abajo). "
               "Criterio 2: positivo y con t > 2, es decir, difícil de explicar por suerte."),
    ("Acierto", "% de compras que acabaron en ganancia. Criterio 3: con un 95 % de confianza, más del 50 %."),
    ("Máx. caída", "La peor bajada desde un máximo hasta un mínimo: cuánto dolor habrías tenido que aguantar."),
]


def _help_panel():
    def items(pairs):
        return html.Ul([html.Li([html.Strong(k + ": "), v]) for k, v in pairs],
                       style={"fontSize": "0.8rem", "paddingLeft": "1.1rem", "marginBottom": "0.4rem"})
    return html.Details([
        html.Summary([html.I(className="fa-solid fa-circle-question me-2", style={"color": "#3ea6ff"}),
                      "¿Cómo leer esta página?"], style={"cursor": "pointer", "fontWeight": 600}),
        html.Div([
            html.P("Cada tarjeta es una idea de inversión (hipótesis) basada en estudios publicados. "
                   "Antes de usarla con dinero se prueba con datos de 2016 a septiembre de 2025 "
                   "(«desarrollo») y, si pasa, una sola vez con el último año («holdout»), que nunca se "
                   "ha mirado, para no hacerse trampas.", style={"fontSize": "0.82rem"}),
            html.Div("Estados", className="kpi-label mb-1"), items(_HELP_ESTADOS),
            html.Div("Números de cada tarjeta", className="kpi-label mb-1"), items(_HELP_METRICAS),
            html.P("Para aceptarla hacen falta los tres criterios a la vez (✔). ✘ indica cuál falla.",
                   className="text-muted", style={"fontSize": "0.78rem", "marginBottom": 0}),
        ], className="mt-2"),
    ], className="mb-3 p-2", style={"border": "1px solid #222", "borderRadius": "6px", "background": "#111"})

_CARD_STYLE = {"border": "1px solid #222", "background": "#111"}


def _pct(v, signed=False) -> str:
    try:
        return f"{float(v) * 100:{'+' if signed else ''}.1f}%"
    except Exception:
        return "—"


def _num(v, d=2) -> str:
    try:
        return f"{float(v):.{d}f}"
    except Exception:
        return "—"


def _result_block(strategy_id: str):
    r = results(strategy_id)
    dev, hold = r["desarrollo"], r["holdout"]
    if dev is None:
        return html.Div("Aún sin medir en el backtest fijo.", className="text-muted",
                        style={"fontSize": "0.8rem"})

    def line(row, title):
        crit1 = float(row["sharpe"]) > float(row["sharpe_bench"])
        crit2 = float(row["ic"]) > 0 and float(row["ic_t"]) > 2
        ok = lambda b: html.Span("✔", style={"color": "#00bc8c"}) if b else html.Span("✘", style={"color": "#e74c3c"})
        return html.Div([
            html.Div(title, style={"fontWeight": 600, "fontSize": "0.78rem", "color": "#ccc"}),
            html.Table([
                html.Tr([html.Td("Rentab. anual"), html.Td(_pct(row["cagr"], True)),
                         html.Td(f"bench {_pct(row['cagr_bench'], True)}", className="text-muted")]),
                html.Tr([html.Td("Sharpe"), html.Td(_num(row["sharpe"])),
                         html.Td(["bench ", _num(row["sharpe_bench"]), " ", ok(crit1)], className="text-muted")]),
                html.Tr([html.Td("IC (t)"), html.Td(f"{_num(row['ic'], 3)} ({_num(row['ic_t'], 1)})"),
                         html.Td(["t > 2 ", ok(crit2)], className="text-muted")]),
                html.Tr([html.Td("Acierto"), html.Td(_pct(row["acierto"])),
                         html.Td(f"{int(row['n_ops'])} operaciones", className="text-muted")]),
                html.Tr([html.Td("Máx. caída"), html.Td(_pct(row["max_dd"])), html.Td("")]),
            ], className="strategy-metrics"),
        ], className="mb-2")

    parts = [line(dev, "Desarrollo (2016 → sep-2025)")]
    if hold is not None:
        parts.append(line(hold, "Holdout (oct-2025 → oct-2026)"))
    return html.Div(parts)


def _strategy_card(s, principal: str):
    est = status(s.id)
    n = attempts(s.id)
    label = f"{est} · intento {n}/{MAX_INTENTOS}" if est == "No aceptada" else est
    badges = [dbc.Badge(label, color=ESTADO_COLOR[est], className="ms-1")]
    if s.id == principal:
        badges.insert(0, dbc.Badge("Principal", color="primary", className="ms-1"))
    if s.recomendada and est != "Descartada":
        badges.insert(0, dbc.Badge("Recomendada", color="success", className="ms-1",
                                   style={"opacity": 0.8}))
    prio = f"Prioridad {s.prioridad}" if s.prioridad < 9 else "Referencia"
    border = "2px solid #3ea6ff" if s.id == principal else "1px solid #222"
    return dbc.Card([
        dbc.CardHeader(html.Div([
            html.Div([html.Strong(s.nombre), html.Div(prio, className="text-muted",
                                                       style={"fontSize": "0.72rem"})]),
            html.Div(badges, className="text-end"),
        ], className="d-flex justify-content-between align-items-start gap-2")),
        dbc.CardBody([
            html.P(s.resumen, style={"fontSize": "0.85rem"}),
            html.Ul([
                html.Li([html.Span("Fuente: ", className="text-muted"), s.fuente]),
                html.Li([html.Span("Universo: ", className="text-muted"), s.universo]),
                html.Li([html.Span("Rebalanceo: ", className="text-muted"), s.rebalanceo]),
            ], style={"fontSize": "0.8rem", "paddingLeft": "1.1rem"}),
            html.P(s.evidencia, className="text-muted", style={"fontSize": "0.76rem"}),
            html.Hr(style={"borderColor": "#222"}),
            _result_block(s.id),
        ]),
    ], style={**_CARD_STYLE, "border": border}, className="h-100")


def _portfolio_rows(strategy_id: str) -> tuple[list[dict], str]:
    data = strategy_runner.load_portfolio(strategy_id)
    if not data:
        return [], "Todavía no se ha calculado. Pulsa «Calcular cartera de hoy»."
    if not data["cartera"]:
        return [], f"Calculada el {data['fecha']}: hoy ninguna empresa tiene señal."
    rows = []
    for i, r in enumerate(data["cartera"], 1):
        rows.append({
            "pos": i, "symbol": r["symbol"], "nombre": r.get("nombre", ""),
            "sector": r.get("sector", ""), "precio": round(r.get("precio", 0), 2),
            "gpa": round(r["gpa"] * 100, 1) if "gpa" in r else None,
            "bm": round(r["bm"], 3) if "bm" in r else None,
            "sorpresa": round(r["score"], 1) if strategy_id == "h2_earnings_surprise" else None,
            "anuncio": r.get("anuncio"),
            "directivos": r.get("directivos"),
            "importe": round(r["importe"] / 1000) if "importe" in r else None,
            "ultima_compra": r.get("ultima_compra"),
        })
    info = (f"Calculada el {data['fecha']} · {data['elegibles']} empresas elegibles · "
            f"estado al calcular: {data['estado']}")
    return rows, info


def _portfolio_cols(strategy_id: str) -> list[dict]:
    cols = [
        {"field": "pos", "headerName": "#", "width": 60},
        {"field": "symbol", "headerName": "Acción", "width": 90},
        {"field": "nombre", "headerName": "Empresa", "flex": 2, "minWidth": 160},
        {"field": "sector", "headerName": "Sector", "flex": 1, "minWidth": 140},
        {"field": "precio", "headerName": "Precio ($)", "width": 110},
    ]
    if strategy_id == "h1_quality_value":
        cols += [{"field": "gpa", "headerName": "Benef. bruto / activos (%)", "width": 190},
                 {"field": "bm", "headerName": "Patrimonio / capitalización", "width": 200}]
    elif strategy_id == "h3_insider_buying":
        cols += [{"field": "directivos", "headerName": "Directivos comprando", "width": 170},
                 {"field": "importe", "headerName": "Importe comprado (miles $)", "width": 200},
                 {"field": "ultima_compra", "headerName": "Última compra", "width": 130}]
    else:
        cols += [{"field": "sorpresa", "headerName": "Sorpresa (%)", "width": 130},
                 {"field": "anuncio", "headerName": "Anuncio", "width": 120}]
    return cols


def _historial_rows() -> list[dict]:
    try:
        h = pd.read_csv(HISTORIAL)
    except Exception:
        return []
    out = []
    for _, r in h.iloc[::-1].iterrows():
        out.append({
            "fecha": f"{str(r['fecha'])[6:8]}-{str(r['fecha'])[4:6]}-{str(r['fecha'])[:4]}",
            "tipo": r["tipo"], "estrategia": NOMBRES_HIST.get(r["variant"], r["variant"]),
            "modelo": r["model"] if r["variant"] in ("base", "earnings_skip_3", "ml20") else "—",
            "cagr": round(r["cagr"] * 100, 1), "cagr_bench": round(r["cagr_bench"] * 100, 1),
            "sharpe": round(r["sharpe"], 2), "sharpe_bench": round(r["sharpe_bench"], 2),
            "ic_t": round(r["ic_t"], 2), "acierto": round(r["acierto"] * 100, 1),
            "aceptado": "Sí" if str(r["aceptado"]) == "True" else "No",
        })
    return out


_HIST_COLS = [
    {"field": "fecha", "headerName": "Fecha", "width": 110},
    {"field": "tipo", "headerName": "Tipo", "width": 110},
    {"field": "estrategia", "headerName": "Estrategia", "flex": 1, "minWidth": 200},
    {"field": "modelo", "headerName": "Modelo", "width": 140},
    {"field": "cagr", "headerName": "Rentab. anual (%)", "width": 150},
    {"field": "cagr_bench", "headerName": "Bench (%)", "width": 110},
    {"field": "sharpe", "headerName": "Sharpe", "width": 100},
    {"field": "sharpe_bench", "headerName": "Sharpe bench", "width": 120},
    {"field": "ic_t", "headerName": "IC t", "width": 90},
    {"field": "acierto", "headerName": "Acierto (%)", "width": 110},
    {"field": "aceptado", "headerName": "Aceptado", "width": 110,
     "cellClassRules": {"badge-comprar": "params.value == 'Sí'", "badge-vender": "params.value == 'No'"}},
]


def layout():
    principal = settings.get("strategy")
    if principal not in BY_ID:
        principal = "h1_quality_value"
    p = BY_ID[principal]
    est = status(principal)
    rows, info = _portfolio_rows(principal) if principal in CARTERA_DISPONIBLE else ([], "")

    gate = dbc.Alert([
        html.I(className="fa-solid fa-shield-halved me-2"),
        html.Strong("Regla de operación: "),
        "una estrategia solo envía órdenes cuando está ", html.Strong("Aprobada"),
        " en el backtest fijo (desarrollo + holdout). Hasta entonces su cartera es teórica. "
        "La compra manual de la pestaña Análisis sigue disponible.",
    ], color="info", className="py-2", style={"fontSize": "0.85rem"})

    cartera_body = (
        [
            html.Div([
                dbc.Button([html.I(className="fa-solid fa-calculator me-2"), "Calcular cartera de hoy"],
                           id="est-calc-btn", color="primary", size="sm", className="me-3"),
                html.Span(id="est-calc-status", className="text-muted", style={"fontSize": "0.8rem"}),
            ], className="mb-2 d-flex align-items-center flex-wrap gap-2"),
            html.Div(info, id="est-portfolio-info", className="text-muted mb-2", style={"fontSize": "0.8rem"}),
            dag.AgGrid(
                id="est-portfolio-grid", columnDefs=_portfolio_cols(principal), rowData=rows,
                defaultColDef={"sortable": True, "resizable": True},
                dashGridOptions={"animateRows": True},
                style={"height": "520px"}, className="ag-theme-alpine-dark",
            ),
        ]
        if principal in CARTERA_DISPONIBLE else
        [html.Div("Esta estrategia no tiene cartera calculable todavía.", className="text-muted")]
    )

    return html.Div([
        dcc.Interval(id="est-poll", interval=3000, disabled=True),
        html.H4("Estrategias", className="page-title"),
        html.Div("Hipótesis pre-registradas en DECISIONS.md, por orden de prioridad. "
                 "El estado lo decide el backtest fijo, no una opinión.", className="page-subtitle"),
        gate,
        _help_panel(),
        dbc.Row([dbc.Col(_strategy_card(s, principal), xs=12, md=6, xl=3, className="mb-3")
                 for s in STRATEGIES], className="g-3"),
        dbc.Card([
            dbc.CardHeader(html.Div([
                html.Div([html.I(className="fa-solid fa-list-ol me-2", style={"color": "#3ea6ff"}),
                          f"Cartera teórica de hoy — {p.nombre}"], style={"fontWeight": 600}),
                dbc.Badge(est, color=ESTADO_COLOR[est]),
            ], className="d-flex justify-content-between align-items-center")),
            dbc.CardBody([
                html.P(["Qué compraría hoy la estrategia ", html.Strong("principal"),
                        " (la que eliges en Configuración) si estuviera aprobada. Es solo informativa: "
                        "no se envía ninguna orden. Se recalcula con el botón."],
                       className="text-muted", style={"fontSize": "0.8rem"}),
                *cartera_body,
            ]),
        ], style=_CARD_STYLE, className="mb-3"),
        dbc.Card([
            dbc.CardHeader(html.Div([html.I(className="fa-solid fa-flask me-2", style={"color": "#3ea6ff"}),
                                     "Historial del backtest fijo"], style={"fontWeight": 600})),
            dbc.CardBody([
                html.P("Registro de todas las pruebas hechas con la misma vara de medir (mismos datos "
                       "congelados, mismas reglas y comisiones), de la más reciente a la más antigua. Sirve "
                       "para comprobar que no se repite una idea ya descartada ni se retocan parámetros hasta "
                       "que salga bien. «Aceptado: Sí» exige los tres criterios.",
                       className="text-muted", style={"fontSize": "0.8rem"}),
                dag.AgGrid(
                    id="est-hist-grid", columnDefs=_HIST_COLS, rowData=_historial_rows(),
                    defaultColDef={"sortable": True, "resizable": True},
                    style={"height": "320px"}, className="ag-theme-alpine-dark",
                ),
            ]),
        ], style=_CARD_STYLE),
        dcc.Store(id="est-principal", data=principal),
    ])


@callback(
    Output("est-poll", "disabled"),
    Output("est-calc-status", "children"),
    Input("est-calc-btn", "n_clicks"),
    State("est-principal", "data"),
    prevent_initial_call=True,
)
def start_calc(n, principal):
    if not n:
        return dash.no_update, dash.no_update
    started = strategy_runner.start(principal)
    msg = ("Calculando… descarga balances y precios de ~400 empresas (1–5 min la primera vez)."
           if started else "Ya hay un cálculo en marcha.")
    return False, [dbc.Spinner(size="sm", color="primary", spinner_class_name="me-2"), msg]


@callback(
    Output("est-calc-status", "children", allow_duplicate=True),
    Output("est-poll", "disabled", allow_duplicate=True),
    Output("est-portfolio-grid", "rowData"),
    Output("est-portfolio-info", "children"),
    Input("est-poll", "n_intervals"),
    State("est-principal", "data"),
    prevent_initial_call=True,
)
def poll_calc(_, principal):
    st = strategy_runner.get_status()
    if st.get("status") == "running":
        return ([dbc.Spinner(size="sm", color="primary", spinner_class_name="me-2"),
                 st.get("last_line", "Calculando…")], False, dash.no_update, dash.no_update)
    rows, info = _portfolio_rows(principal)
    if st.get("status") == "error":
        return (html.Span("Error al calcular (ver estrategia_cartera.log).", style={"color": "#e74c3c"}),
                True, rows, info)
    return (html.Span(f"Listo ({st.get('finished_at', '')}).", style={"color": "#00bc8c"}),
            True, rows, info)
