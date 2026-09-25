"""Разговор с ботом. Кнопки воды, пошаговый опрос, отбой и подъём."""

from datetime import datetime

from sqlalchemy.orm import Session

from app import telegram as tg
from app.config import TELEGRAM_CHAT_ID, TZ
from app.models import BotState, Day, Observation, Profile
from app.security import is_owner_update, is_start_command

GLASS = 0.25
BOTTLE = 0.5

# Порядок вечернего опроса. Спрашивается только то, что не отмечено.
EVENING_STEPS = ["gym", "spent", "study", "food"]


def get_state(session: Session) -> BotState:
    state = session.get(BotState, 1)
    if state is None:
        state = BotState(id=1)
        session.add(state)
        session.commit()
    return state


def set_state(session: Session, step=None, awaiting=None, queue=None):
    state = get_state(session)
    state.step = step
    state.awaiting = awaiting
    state.queue = queue
    state.updated_at = datetime.utcnow()
    session.commit()


def water_markup() -> dict:
    return tg.keyboard([
        [("Стакан", "water:250"), ("Бутылка", "water:500")],
        [("Минус стакан", "water:-250"), ("Пропустить", "water:skip")],
    ])


def water_done(day: Day, profile: Profile) -> str:
    """Короткая отписка вместо кнопок после нажатия."""
    import random

    target = profile.water_target_l or 2.5
    left = round(target - day.water_l, 2)
    if left <= 0:
        return f"Записала. {day.water_l} л, норма взята."
    lines = [
        f"Записала. {day.water_l} л, осталось {left}.",
        f"Есть. Уже {day.water_l} л из {target}.",
        f"Отметила: {day.water_l} л. До нормы {left}.",
    ]
    return random.choice(lines)


def water_text(day: Day, profile: Profile) -> str:
    target = profile.water_target_l or 2.5
    left = max(0, round(target - day.water_l, 2))
    if left <= 0:
        return f"Вода: {day.water_l} л. Норма взята."
    return f"Вода: {day.water_l} из {target} л. Осталось {left}."


# ---------- обработка входящих ----------


def handle_update(session: Session, update: dict, day_getter) -> None:
    if not is_owner_update(update, TELEGRAM_CHAT_ID):
        # Чужие сообщения молча игнорируем. Исключение одно: пока номер
        # владельца не настроен, на /start бот подсказывает номер чата.
        if not TELEGRAM_CHAT_ID and is_start_command(update):
            send_chat_id(update["message"])
        return

    if "callback_query" in update:
        handle_callback(session, update["callback_query"], day_getter)
    elif "message" in update:
        handle_message(session, update["message"], day_getter)


def handle_callback(session: Session, query: dict, day_getter) -> None:
    data = query.get("data", "")
    chat_id = query["message"]["chat"]["id"]
    message_id = query["message"]["message_id"]
    day = day_getter(session)
    profile = session.get(Profile, 1) or Profile(id=1)

    action, _, value = data.partition(":")

    if action == "water":
        if value == "skip":
            tg.answer_callback(query["id"])
            tg.edit(chat_id, message_id, "Ладно, потом.")
            return

        day.water_l = round(max(0.0, day.water_l + int(value) / 1000), 2)
        session.commit()
        tg.answer_callback(query["id"])
        tg.edit(chat_id, message_id, water_done(day, profile))
        return

    if action == "gym":
        day.gym = value == "1"
        session.commit()
        tg.answer_callback(query["id"])
        tg.edit(chat_id, message_id, "Зал: " + ("был" if day.gym else "не был"))
        if not day.gym:
            ask_reason(session, "gym")
        else:
            next_step(session, day)
        return

    if action == "spent":
        if value == "own":
            set_state(session, step="spent", awaiting="spent")
            tg.answer_callback(query["id"])
            tg.edit(chat_id, message_id, "Сколько?")
            return
        day.spent = float(value)
        session.commit()
        tg.answer_callback(query["id"])
        tg.edit(chat_id, message_id, f"Траты: {int(day.spent)} ₽")
        next_step(session, day)
        return

    if action == "study":
        if value == "own":
            set_state(session, step="study", awaiting="study")
            tg.answer_callback(query["id"])
            tg.edit(chat_id, message_id, "Сколько минут?")
            return
        day.study_min = int(value)
        session.commit()
        tg.answer_callback(query["id"])
        tg.edit(chat_id, message_id, f"Учёба: {day.study_min} мин")
        next_step(session, day)
        return

    if action == "bed":
        tg.answer_callback(query["id"])
        if value == "ok":
            tg.edit(chat_id, message_id, "Понял. Спокойной.")
        else:
            set_state(session, step="bed", awaiting="bed_reason")
            tg.edit(chat_id, message_id, "Ладно. А почему сдвигаешь?")
        return

    if action == "skip":
        tg.answer_callback(query["id"])
        tg.edit(chat_id, message_id, "Пропустил.")
        next_step(session, day)
        return

    tg.answer_callback(query["id"])


def handle_message(session: Session, message: dict, day_getter) -> None:
    from app import brain

    text = (message.get("text") or "").strip()

    voice = message.get("voice") or message.get("audio") or message.get("video_note")
    if voice and not text:
        tg.send_typing()
        url = tg.get_file_url(voice.get("file_id", ""))
        text = brain.transcribe(url) if url else None
        if not text:
            tg.send("Не разобрала голосовое. Напиши текстом.")
            return

    if not text:
        return

    if text.startswith("/start"):
        send_chat_id(message)
        return

    state = get_state(session)
    day = day_getter(session)

    if state.awaiting == "spent":
        day.spent = to_number(text)
        session.commit()
        tg.send(f"Записал: {int(day.spent)} ₽")
        next_step(session, day)
        return

    if state.awaiting == "study":
        day.study_min = int(to_number(text))
        session.commit()
        tg.send(f"Записал: {day.study_min} мин")
        next_step(session, day)
        return

    if state.awaiting == "morning":
        set_state(session)
        if day.wake_at is None:
            day.wake_at = datetime.now(TZ).time().replace(second=0, microsecond=0)
            session.commit()
        tg.send(brain.ask(session, text, day_getter, source="telegram"))
        return

    if state.awaiting == "wake":
        hours, _, minutes = text.replace(".", ":").partition(":")
        try:
            from datetime import time as _time

            day.wake_at = _time(int(hours), int(minutes or 0))
            session.commit()
            tg.send("Принял. Хорошего дня.")
        except ValueError:
            tg.send("Не разобрал время. Напиши как 7:30.")
            return
        set_state(session)
        return

    if state.awaiting in ("gym_reason", "bed_reason"):
        topic = "gym" if state.awaiting == "gym_reason" else "sleep"
        session.add(
            Observation(
                date=day.date, topic=topic, kind="reason", text=text[:500]
            )
        )
        session.commit()
        queue = get_state(session).queue
        tg.send(reason_reply(session, topic, text))
        if topic == "gym":
            set_state(session, step="gym", queue=queue)
            next_step(session, day)
        else:
            set_state(session)
        return

    if state.awaiting == "food":
        day.note = ((day.note or "") + " | " + text).strip(" |")
        session.commit()
        tg.send("Записал. Калории посчитаю, когда подключим расчёт.")
        set_state(session)
        return

    tg.send_typing()
    tg.send(brain.ask(session, text, day_getter, source="telegram"))


def send_chat_id(message: dict) -> None:
    chat_id = message["chat"]["id"]
    tg.send(
        "На связи. Твой номер чата: <code>%s</code>\n"
        "Впиши его в настройки, и я начну напоминать." % chat_id,
        chat_id=str(chat_id),
    )


def to_number(text: str) -> float:
    cleaned = "".join(c for c in text.replace(",", ".") if c.isdigit() or c == ".")
    try:
        return float(cleaned or 0)
    except ValueError:
        return 0.0


# ---------- пошаговый опрос ----------


def start_evening(session: Session, day: Day) -> None:
    pending = [s for s in EVENING_STEPS if not filled(day, s)]
    if not pending:
        tg.send("Всё уже отмечено. Отдыхай.")
        return
    set_state(session, queue=",".join(pending))
    ask(session, day, pending[0])


def filled(day: Day, step: str) -> bool:
    if step == "gym":
        return day.gym is not None
    if step == "spent":
        return bool(day.spent)
    if step == "study":
        return bool(day.study_min)
    if step == "food":
        return bool(day.meals) or bool(day.note)
    return True


def next_step(session: Session, day: Day) -> None:
    state = get_state(session)
    queue = [s for s in (state.queue or "").split(",") if s]
    while queue and (queue[0] == state.step or filled(day, queue[0])):
        queue.pop(0)
    if not queue:
        set_state(session)
        tg.send(summary(day))
        return
    set_state(session, queue=",".join(queue))
    ask(session, day, queue[0])


def ask(session: Session, day: Day, step: str) -> None:
    set_state(session, step=step, queue=get_state(session).queue)

    if step == "gym":
        tg.send("Зал сегодня?", tg.keyboard([
            [("Был", "gym:1"), ("Не был", "gym:0")],
        ]))
    elif step == "spent":
        tg.send("Сколько потратил?", tg.keyboard([
            [("Нисколько", "spent:0"), ("500", "spent:500")],
            [("1000", "spent:1000"), ("Своя сумма", "spent:own")],
        ]))
    elif step == "study":
        tg.send("Учёба сегодня?", tg.keyboard([
            [("Не было", "study:0"), ("30 мин", "study:30")],
            [("Час", "study:60"), ("Своё", "study:own")],
        ]))
    elif step == "food":
        set_state(session, step="food", awaiting="food", queue=get_state(session).queue)
        tg.send("Что ел за день? Напиши одной строкой.")


def ask_reason(session: Session, topic: str) -> None:
    set_state(session, step=topic, awaiting=f"{topic}_reason", queue=get_state(session).queue)
    tg.send("А что помешало?")


def reason_reply(session: Session, topic: str, text: str) -> str:
    """Пока без модели: считаем повторы и отвечаем по правилу."""
    recent = (
        session.query(Observation)
        .filter(Observation.topic == topic, Observation.kind == "reason")
        .order_by(Observation.date.desc())
        .limit(3)
        .all()
    )
    weak = ("лень", "устал", "не хотел", "не хочу", "настроени")
    is_weak = any(w in text.lower() for w in weak)

    if is_weak and len(recent) >= 3:
        return "Третий раз подряд одно и то же. Завтра ставим полчаса вместо часа, но идём."
    if is_weak:
        return "Записал. Но давай завтра всё-таки сходим."
    return "Понял, причина уважительная. Записал."


def summary(day: Day) -> str:
    parts = [f"Вода {day.water_l} л"]
    if day.gym is not None:
        parts.append("зал был" if day.gym else "зала не было")
    if day.spent:
        parts.append(f"траты {int(day.spent)} ₽")
    if day.study_min:
        parts.append(f"учёба {day.study_min} мин")
    return "День закрыт: " + ", ".join(parts) + "."


# ---------- инициатива бота ----------


def send_water(session: Session, day: Day) -> None:
    profile = session.get(Profile, 1) or Profile(id=1)
    tg.send(water_text(day, profile), water_markup())


def send_bedtime(session: Session, profile: Profile) -> None:
    target = profile.sleep_target.strftime("%H:%M")
    tg.send(
        f"Полчаса до отбоя. По плану в {target}.",
        tg.keyboard([[("Ложусь", "bed:ok"), ("Сдвигаю", "bed:shift")]]),
    )


MORNING_LINES = [
    "Доброе. Как спалось?",
    "Утро. Ты живой там?",
    "Проснулся? Рассказывай, как ночь.",
    "Доброе утро. Готов к дню или ещё не очень?",
]

LATE_MORNING_LINES = [
    "Ну ты и поспал. Проспал или так и было задумано?",
    "Утро уже кончается. Только встал?",
    "Долго. Что случилось, поздно лёг?",
]


def send_morning(session: Session, late: bool = False) -> None:
    """Никаких кнопок: любой твой ответ означает, что ты встал."""
    import random

    set_state(session, step="morning", awaiting="morning")
    lines = LATE_MORNING_LINES if late else MORNING_LINES
    tg.send(random.choice(lines))


def now_local() -> datetime:
    return datetime.now(TZ)
