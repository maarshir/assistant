"""Настройки для тестов задаются до импорта приложения: config читает их при загрузке."""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_db_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_db_dir, "test.db")
os.environ["TELEGRAM_TOKEN"] = "123456:TEST-TOKEN"
os.environ["TELEGRAM_CHAT_ID"] = "111"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = ""
os.environ["LLM_API_KEY"] = ""

import pytest  # noqa: E402

from app import telegram as tg  # noqa: E402

OWNER_ID = 111
STRANGER_ID = 999


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Вместо запросов к Телеграму складываем вызовы в список."""
    calls = []

    def fake_post(method, payload):
        calls.append((method, payload))
        return {"ok": True, "result": {}}

    monkeypatch.setattr(tg, "_post", fake_post)
    return calls
