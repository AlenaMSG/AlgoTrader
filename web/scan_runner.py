"""
Gestiona el proceso de scan manual del S&P 100 como subproceso.
Mantiene estado en scan_status.json para que los callbacks de Dash puedan consultarlo.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
STATUS_FILE = ROOT / "scan_status.json"

_proc: subprocess.Popen | None = None


def start_scan() -> bool:
    """Lanza scan_sp100.py en segundo plano. Devuelve False si ya hay uno corriendo."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        return False
    _write_status("running")
    _proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scan_sp100.py")],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


def get_status() -> dict:
    """Devuelve el estado actual del scan: idle | running | done | error."""
    _refresh()
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "idle"}


def _refresh() -> None:
    global _proc
    if _proc is None:
        return
    rc = _proc.poll()
    if rc is not None:
        status = "done" if rc == 0 else "error"
        _write_status(status, returncode=rc)
        _proc = None


def _write_status(status: str, **extra) -> None:
    STATUS_FILE.write_text(
        json.dumps({
            "status": status,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            **extra,
        }),
        encoding="utf-8",
    )
