import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, callback, Output, Input


NAV_ITEMS = [
    ("Inicio",         "/",               "fa-house"),
    ("Análisis",       "/analisis",       "fa-magnifying-glass-chart"),
    ("Estrategias",    "/estrategias",    "fa-chess-knight"),
    ("Precio",         "/precio",         "fa-chart-candlestick"),
    ("Cartera",        "/cartera",        "fa-briefcase"),
    ("Historial",      "/historial",      "fa-clock-rotate-left"),
    ("Comparación",    "/comparacion",    "fa-chart-bar"),
    ("Configuración",  "/configuracion",  "fa-sliders"),
]


def create_layout():
    nav_links = [
        dbc.NavItem(
            dbc.NavLink(
                [html.I(className=f"fa-solid {icon} me-1"), label],
                href=href,
                active="exact",
                class_name="nav-link-custom",
            )
        )
        for label, href, icon in NAV_ITEMS
    ]

    navbar = dbc.Navbar(
        dbc.Container(
            [
                dbc.NavbarBrand(
                    [html.I(className="fa-solid fa-chart-line me-2"), "AlgoTrader"],
                    href="/",
                    class_name="navbar-brand-custom",
                ),
                dbc.NavbarToggler(id="navbar-toggler"),
                dbc.Collapse(
                    dbc.Nav(nav_links, navbar=True, class_name="ms-auto"),
                    id="navbar-collapse",
                    navbar=True,
                ),
            ],
            fluid=True,
        ),
        color="dark",
        dark=True,
        sticky="top",
        class_name="shadow-sm mb-0",
    )

    return html.Div(
        [
            dcc.Location(id="url"),
            navbar,
            dbc.Container(
                dash.page_container,
                fluid=True,
                class_name="px-3 px-md-4 pt-3 pb-5",
            ),
        ]
    )


@callback(
    Output("navbar-collapse", "is_open"),
    Input("navbar-toggler", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_navbar(n):
    return bool(n % 2) if n else False
