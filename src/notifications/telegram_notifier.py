"""
Envío de mensajes a Telegram vía Bot API.
Requiere TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en .env.
Uso:
    from src.notifications.telegram_notifier import send_alert
    send_alert(token, chat_id, "<b>Texto HTML</b>")
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def send_alert(token: str, chat_id: str, text: str) -> bool:
    """
    Envía `text` (HTML) al chat `chat_id` usando el bot `token`.
    Devuelve True si tuvo éxito, False en caso contrario.
    """
    if not token or not chat_id:
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.ok:
            logger.info("Telegram: mensaje enviado correctamente")
            return True
        logger.warning(f"Telegram: error {resp.status_code} — {resp.text[:200]}")
        return False
    except Exception as exc:
        logger.warning(f"Telegram: excepción al enviar — {exc}")
        return False
