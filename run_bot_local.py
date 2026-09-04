"""Локальный запуск бота. В облаке вместо этого работают вебхук и внешний планировщик.

Запуск: python run_bot_local.py
"""

import signal
import time as clock
import traceback
from datetime import datetime

from app import bot as botlogic
from app import reminders
from app import telegram as tg
from app.config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN, TZ
from app.db import SessionLocal, init_db
from app.main import get_day

LAST_TICK = 0
STOP = False


def request_stop(signum, frame):
    global STOP
    STOP = True
    print("\nОстанавливаюсь, доделываю текущий запрос...")


def main():
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    if not TELEGRAM_TOKEN:
        print("Не заполнен TELEGRAM_TOKEN в .env")
        return
    if not TELEGRAM_CHAT_ID:
        print("Не заполнен TELEGRAM_CHAT_ID. Напиши боту /start, он подскажет номер.")

    init_db()
    tg.delete_webhook()
    print("Бот слушает. Остановить: Ctrl+C")

    offset = None
    global LAST_TICK

    while not STOP:
        try:
            for update in tg.get_updates(offset):
                if STOP:
                    break
                offset = update["update_id"] + 1
                with SessionLocal() as session:
                    botlogic.handle_update(session, update, get_day)

            if clock.time() - LAST_TICK > 60:
                LAST_TICK = clock.time()
                with SessionLocal() as session:
                    sent = reminders.tick(session, get_day)
                if sent:
                    stamp = datetime.now(TZ).strftime("%H:%M")
                    print(f"{stamp} отправлено: {', '.join(sent)}")

        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
            clock.sleep(5)

    print("Бот остановлен.")


if __name__ == "__main__":
    main()
