from pathlib import Path
import dash
import dash_bootstrap_components as dbc

PAGES_DIR = str(Path(__file__).parent / "pages")

app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder=PAGES_DIR,
    external_stylesheets=[
        dbc.themes.CYBORG,
        dbc.icons.FONT_AWESOME,
    ],
    title="AlgoTrader",
    update_title=None,
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
    ],
)
server = app.server

from web.layout import create_layout  # noqa: E402 — after app init
app.layout = create_layout()
