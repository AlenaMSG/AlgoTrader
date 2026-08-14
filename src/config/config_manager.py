from pathlib import Path
import os
from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE     = PROJECT_ROOT / ".env"
README_DIR   = PROJECT_ROOT / "Readme"
CONFIG_FILE  = README_DIR / "config.txt"   # legado — se mantiene por compatibilidad


class ConfigManager:
    def __init__(self):
        README_DIR.mkdir(exist_ok=True)
        load_dotenv(ENV_FILE, override=False)  # carga .env en os.environ si existe

    def has_valid_config(self) -> bool:
        k, s = self.get_credentials()
        return bool(k) and bool(s)

    def get_credentials(self) -> tuple[str, str]:
        # Prioridad: .env / variables de entorno → config.txt legado
        api_key    = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")

        if not api_key or not secret_key:
            legacy = self._read_legacy()
            api_key    = api_key    or legacy.get("API_KEY", "")
            secret_key = secret_key or legacy.get("SECRET_KEY", "")

        return api_key, secret_key

    def save_config(self, api_key: str, secret_key: str) -> None:
        api_key    = api_key.strip()
        secret_key = secret_key.strip()

        # Guardar en .env (fuente principal)
        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), "ALPACA_API_KEY",    api_key)
        set_key(str(ENV_FILE), "ALPACA_SECRET_KEY", secret_key)

        # Actualizar os.environ en la sesión actual
        os.environ["ALPACA_API_KEY"]    = api_key
        os.environ["ALPACA_SECRET_KEY"] = secret_key

        # Mantener config.txt por compatibilidad
        CONFIG_FILE.write_text(
            f"API_KEY={api_key}\nSECRET_KEY={secret_key}\n",
            encoding="utf-8",
        )

    def _read_legacy(self) -> dict:
        if not CONFIG_FILE.exists():
            return {}
        result = {}
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
        return result
