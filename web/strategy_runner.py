"""
Lanza estrategia_cartera.py como subproceso (cartera teórica de hoy) y expone su estado
y el resultado (strategy_portfolio.json) a los callbacks de Dash.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
PORTFOLIO_FILE = ROOT / "strategy_portfolio.json"
LOG_FILE = ROOT / "estrategia_cartera.log"

_proc: subprocess.Popen | None = None
_state: dict = {"status": "idle"}


def start(strategy_id: str) -> bool:
    """Devuelve False si ya hay un cálculo en marcha."""
    global _proc, _state
    if _proc is not None and _proc.poll() is None:
        return False
    log = LOG_FILE.open("w", encoding="utf-8")
    _proc = subprocess.Popen(
        [sys.executable, str(ROOT / "estrategia_cartera.py"), "--strategy", strategy_id],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    _state = {"status": "running", "strategy": strategy_id,
              "started_at": datetime.now().strftime("%H:%M:%S")}
    return True


def get_status() -> dict:
    global _proc, _state
    if _proc is not None and _proc.poll() is not None:
        _state = {**_state, "status": "done" if _proc.returncode == 0 else "error",
                  "finished_at": datetime.now().strftime("%H:%M:%S")}
        _proc = None
    if _state.get("status") == "running":
        try:
            lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
            _state["last_line"] = lines[-1][-120:] if lines else ""
        except Exception:
            pass
    return dict(_state)


def load_portfolio(strategy_id: str) -> dict | None:
    try:
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8")).get(strategy_id)
    except Exception:
        return None
