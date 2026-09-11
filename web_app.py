"""
AlgoTrader Web Dashboard
Lanzar con: .\.venv\Scripts\python.exe web_app.py
Abrir en:   http://localhost:8050
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from web.app import app

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AlgoTrader Web Dashboard")
    parser.add_argument("--host",  default="0.0.0.0",  help="Host (default 0.0.0.0)")
    parser.add_argument("--port",  default=8050, type=int, help="Port (default 8050)")
    parser.add_argument("--debug", action="store_true",   help="Enable debug mode")
    args = parser.parse_args()

    print(f"\n  AlgoTrader Dashboard → http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
