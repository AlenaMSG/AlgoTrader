from pathlib import Path

README_DIR = Path(__file__).resolve().parents[3] / "Readme"
CONFIG_FILE = README_DIR / "config.txt"


class ConfigManager:
    def __init__(self):
        README_DIR.mkdir(exist_ok=True)

    def has_valid_config(self) -> bool:
        if not CONFIG_FILE.exists():
            return False
        cfg = self._read_raw()
        return bool(cfg.get("API_KEY")) and bool(cfg.get("SECRET_KEY"))

    def get_credentials(self) -> tuple[str, str]:
        cfg = self._read_raw()
        return cfg.get("API_KEY", ""), cfg.get("SECRET_KEY", "")

    def save_config(self, api_key: str, secret_key: str) -> None:
        lines = [
            f"API_KEY={api_key.strip()}\n",
            f"SECRET_KEY={secret_key.strip()}\n",
        ]
        CONFIG_FILE.write_text("".join(lines), encoding="utf-8")

    def _read_raw(self) -> dict:
        if not CONFIG_FILE.exists():
            return {}
        result = {}
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
        return result
