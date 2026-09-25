"""Проверки доступа на уровне приложения: бот, вход из Телеграма, вебхук."""

import pytest
from fastapi.testclient import TestClient

from app import bot, main
from app.db import SessionLocal, init_db
from app.models import Day
from conftest import OWNER_ID, STRANGER_ID
from test_security import callback, message, signed_init_data

init_db()


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def water_today():
    with SessionLocal() as s:
        return main.get_day(s).water_l


# ---------- бот ----------


def test_stranger_message_is_ignored(no_network):
    with SessionLocal() as s:
        bot.handle_update(s, message(STRANGER_ID, STRANGER_ID, "/start"), main.get_day)
        bot.handle_update(s, message(STRANGER_ID, STRANGER_ID, "выпил литр"), main.get_day)
    assert no_network == []


def test_stranger_button_does_not_change_day(no_network):
    before = water_today()
    with SessionLocal() as s:
        bot.handle_update(s, callback(STRANGER_ID, STRANGER_ID, "water:500"), main.get_day)
    assert water_today() == before
    assert no_network == []


def test_owner_button_changes_day(no_network):
    before = water_today()
    with SessionLocal() as s:
        bot.handle_update(s, callback(OWNER_ID, OWNER_ID, "water:250"), main.get_day)
    assert water_today() == round(before + 0.25, 2)
    assert any(method == "editMessageText" for method, _ in no_network)


def test_owner_start_gets_answer(no_network):
    with SessionLocal() as s:
        bot.handle_update(s, message(OWNER_ID, OWNER_ID, "/start"), main.get_day)
    assert [m for m, _ in no_network] == ["sendMessage"]


def test_without_owner_setting_only_start_answers(no_network, monkeypatch):
    monkeypatch.setattr(bot, "TELEGRAM_CHAT_ID", "")
    with SessionLocal() as s:
        bot.handle_update(s, message(STRANGER_ID, STRANGER_ID, "выпил литр"), main.get_day)
        assert no_network == []
        bot.handle_update(s, message(STRANGER_ID, STRANGER_ID, "/start"), main.get_day)
    assert len(no_network) == 1
    method, payload = no_network[0]
    assert method == "sendMessage"
    assert payload["chat_id"] == str(STRANGER_ID)
    assert str(STRANGER_ID) in payload["text"]


# ---------- вход из окна Телеграма ----------


def test_tg_auth_owner_gets_cookie(client):
    r = client.post("/api/tg-auth", json={"init_data": signed_init_data(OWNER_ID)})
    assert r.status_code == 200
    assert main.COOKIE in r.headers.get("set-cookie", "")


def test_tg_auth_stranger_is_rejected(client):
    r = client.post("/api/tg-auth", json={"init_data": signed_init_data(STRANGER_ID)})
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


def test_tg_auth_bad_signature(client):
    r = client.post("/api/tg-auth", json={"init_data": signed_init_data(OWNER_ID, "x:y")})
    assert r.status_code == 403


def test_tg_auth_without_owner_setting_rejects_everyone(client, monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_CHAT_ID", "")
    r = client.post("/api/tg-auth", json={"init_data": signed_init_data(OWNER_ID)})
    assert r.status_code == 403


def test_tg_auth_empty_body(client):
    assert client.post("/api/tg-auth", json={}).status_code == 400


# ---------- вебхук ----------


def test_webhook_without_secret_works_as_before(client, no_network):
    r = client.post("/api/telegram/webhook", json=message(OWNER_ID, OWNER_ID, "/start"))
    assert r.status_code == 200
    assert len(no_network) == 1


def test_webhook_rejects_wrong_secret(client, no_network, monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    before = water_today()
    r = client.post(
        "/api/telegram/webhook",
        json=callback(OWNER_ID, OWNER_ID, "water:500"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert r.status_code == 401
    r = client.post("/api/telegram/webhook", json=callback(OWNER_ID, OWNER_ID, "water:500"))
    assert r.status_code == 401
    assert water_today() == before
    assert no_network == []


def test_webhook_accepts_right_secret(client, no_network, monkeypatch):
    monkeypatch.setattr(main, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    r = client.post(
        "/api/telegram/webhook",
        json=message(OWNER_ID, OWNER_ID, "/start"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert r.status_code == 200
    assert len(no_network) == 1


def test_webhook_stranger_gets_ok_but_nothing_happens(client, no_network):
    # Телеграму отвечаем 200, иначе он будет повторять доставку.
    r = client.post("/api/telegram/webhook", json=message(STRANGER_ID, STRANGER_ID, "привет"))
    assert r.status_code == 200
    assert no_network == []


def test_set_webhook_passes_secret(no_network, monkeypatch):
    from app import telegram as tg

    monkeypatch.setattr(tg, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    tg.set_webhook("https://example.com/api/telegram/webhook")
    assert no_network[-1][1]["secret_token"] == "s3cret"
