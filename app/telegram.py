"""Тонкая обёртка над Телеграмом. Только отправка и кнопки, без логики."""

import httpx

from app.config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def _post(method: str, payload: dict) -> dict | None:
    if not TELEGRAM_TOKEN:
        return None
    try:
        r = httpx.post(f"{API}/{method}", json=payload, timeout=15)
        return r.json()
    except httpx.HTTPError:
        return None


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """rows: список рядов, каждая кнопка это пара (надпись, код)."""
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": data} for text, data in row]
            for row in rows
        ]
    }


def link_keyboard(text: str, url: str) -> dict:
    return {"inline_keyboard": [[{"text": text, "url": url}]]}


def send(text: str, markup: dict | None = None, chat_id: str | None = None):
    payload = {
        "chat_id": chat_id or TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if markup:
        payload["reply_markup"] = markup
    return _post("sendMessage", payload)


def edit(chat_id: int, message_id: int, text: str, markup: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if markup:
        payload["reply_markup"] = markup
    return _post("editMessageText", payload)


def answer_callback(callback_id: str, text: str = ""):
    return _post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def set_webhook(url: str):
    return _post("setWebhook", {"url": url, "allowed_updates": ["message", "callback_query"]})


def delete_webhook():
    return _post("deleteWebhook", {})


def get_updates(offset: int | None = None):
    """Только для локальной разработки, в облаке работает вебхук."""
    if not TELEGRAM_TOKEN:
        return []
    params = {"timeout": 3}
    if offset:
        params["offset"] = offset
    try:
        r = httpx.get(f"{API}/getUpdates", params=params, timeout=10)
        return r.json().get("result", [])
    except httpx.HTTPError:
        return []
