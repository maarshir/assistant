import hashlib
import hmac
import json
from urllib.parse import urlencode

from app import security
from conftest import OWNER_ID, STRANGER_ID

TOKEN = "123456:TEST-TOKEN"


def signed_init_data(user_id, token=TOKEN):
    """Собирает init_data так же, как это делает Телеграм."""
    fields = {
        "auth_date": "1790000000",
        "query_id": "AAE",
        "user": json.dumps({"id": user_id, "first_name": "Тест"}),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def message(chat_id, user_id, text="привет"):
    return {"message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": text}}


def callback(chat_id, user_id, data="water:250"):
    return {
        "callback_query": {
            "id": "1",
            "data": data,
            "from": {"id": user_id},
            "message": {"message_id": 5, "chat": {"id": chat_id}},
        }
    }


def test_same_id_compares_number_and_string():
    assert security.same_id(111, "111")
    assert security.same_id("111", " 111 ")
    assert not security.same_id(112, "111")
    assert not security.same_id(111, "")
    assert not security.same_id(None, "111")


def test_owner_message_and_callback_pass():
    assert security.is_owner_update(message(OWNER_ID, OWNER_ID), "111")
    assert security.is_owner_update(callback(OWNER_ID, OWNER_ID), "111")


def test_stranger_is_rejected():
    assert not security.is_owner_update(message(STRANGER_ID, STRANGER_ID), "111")
    assert not security.is_owner_update(callback(STRANGER_ID, STRANGER_ID), "111")


def test_owner_chat_but_other_sender_is_rejected():
    # Например, группа с тем же номером или подделанное обновление.
    assert not security.is_owner_update(message(OWNER_ID, STRANGER_ID), "111")
    assert not security.is_owner_update(callback(OWNER_ID, STRANGER_ID), "111")


def test_missing_fields_and_empty_owner_are_rejected():
    assert not security.is_owner_update({}, "111")
    assert not security.is_owner_update({"message": {"text": "hi"}}, "111")
    assert not security.is_owner_update(message(OWNER_ID, OWNER_ID), "")


def test_start_command_detection():
    assert security.is_start_command(message(1, 1, "/start"))
    assert not security.is_start_command(message(1, 1, "старт"))
    assert not security.is_start_command(callback(1, 1))


def test_init_data_signature():
    fields = security.check_init_data(signed_init_data(OWNER_ID), TOKEN)
    assert fields is not None
    assert security.init_data_user_id(fields) == OWNER_ID


def test_init_data_wrong_token_or_tampered():
    assert security.check_init_data(signed_init_data(OWNER_ID, "other:token"), TOKEN) is None
    tampered = signed_init_data(STRANGER_ID).replace(str(STRANGER_ID), str(OWNER_ID))
    assert security.check_init_data(tampered, TOKEN) is None
    assert security.check_init_data("", TOKEN) is None
    assert security.check_init_data("not a query", TOKEN) is None
    assert security.check_init_data("a=1&b=2", TOKEN) is None


def test_init_data_user_id_bad_json():
    assert security.init_data_user_id({"user": "{broken"}) is None
    assert security.init_data_user_id({}) is None


def test_webhook_secret():
    assert security.webhook_secret_ok(None, "")
    assert security.webhook_secret_ok("что угодно", "")
    assert security.webhook_secret_ok("s3cret", "s3cret")
    assert not security.webhook_secret_ok("wrong", "s3cret")
    assert not security.webhook_secret_ok(None, "s3cret")
