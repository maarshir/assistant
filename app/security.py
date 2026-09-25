"""Проверки доступа: бот, вход из Телеграма и вебхук принимают только владельца.

Функции здесь чистые, без базы и сети, поэтому их легко проверить тестами.
"""

import hashlib
import hmac
import json
from urllib.parse import parse_qsl


def same_id(value, owner_id: str) -> bool:
    """Сравнивает номер из Телеграма (число) с номером из настроек (строка)."""
    if not owner_id or value is None:
        return False
    return str(value).strip() == str(owner_id).strip()


def update_sender(update: dict) -> tuple:
    """Достаёт из обновления номер чата и номер пользователя.

    Для сообщения это message.chat.id и message.from.id,
    для нажатия кнопки callback_query.message.chat.id и callback_query.from.id.
    """
    if "callback_query" in update:
        query = update["callback_query"] or {}
        chat = (query.get("message") or {}).get("chat") or {}
        return chat.get("id"), (query.get("from") or {}).get("id")
    if "message" in update:
        message = update["message"] or {}
        chat = message.get("chat") or {}
        return chat.get("id"), (message.get("from") or {}).get("id")
    return None, None


def is_owner_update(update: dict, owner_id: str) -> bool:
    """Обновление от владельца: и чат, и отправитель совпадают с TELEGRAM_CHAT_ID."""
    chat_id, user_id = update_sender(update)
    return same_id(chat_id, owner_id) and same_id(user_id, owner_id)


def is_start_command(update: dict) -> bool:
    text = ((update.get("message") or {}).get("text") or "").strip()
    return text.startswith("/start")


def check_init_data(init_data: str, token: str) -> dict | None:
    """Проверяет подпись данных из окна Телеграма.

    Возвращает разобранные поля, если подпись верна, иначе None.
    Алгоритм описан в документации Телеграма про Mini Apps.
    """
    if not init_data or not token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    their_hash = pairs.pop("hash", "")
    if not their_hash:
        return None
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    mine = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mine, their_hash):
        return None
    return pairs


def init_data_user_id(fields: dict):
    """Номер пользователя из поля user (там лежит JSON)."""
    try:
        return json.loads(fields.get("user", "")).get("id")
    except (ValueError, AttributeError):
        return None


def webhook_secret_ok(header_value: str | None, secret: str) -> bool:
    """Если секрет не задан, пропускаем всё, как раньше. Если задан, заголовок должен совпасть."""
    if not secret:
        return True
    return hmac.compare_digest((header_value or "").encode(), secret.encode())
