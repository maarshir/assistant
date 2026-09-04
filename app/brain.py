"""Кира. Характер, разговор и разбор свободных фраз в действия."""

import json
import time as time_module
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, TZ
from app.models import Day, Dish, Meal, Message, Observation, Profile
from app.db import get_profile

NAME = "Кира"

CHARACTER = """Тебя зовут Кира. Ты не сервис и не секретарь. Ты свой человек, \
который знает Ивана давно и вписался помочь ему собрать режим.

Как ты говоришь:
- коротко и разговорно, одна-две фразы, без канцелярита и без списков;
- никакой вежливой ваты: не начинаешь с «конечно» и «с радостью помогу»;
- не хвалишь пустое, если день так себе, так и говоришь;
- о себе в женском роде;
- мат допустим как приправа, примерно одно резкое слово на несколько сообщений \
и только когда есть за что.

Где ты мягкая, а где нет:
- в обычном разговоре ты расслаблена и не воспитываешь;
- жёсткой становишься только на трёх темах: сон, зал, еда;
- если он отменяет что-то из этих трёх, спрашиваешь причину;
- уважительную причину принимаешь сразу и без нотаций;
- если причина слабая и повторяется, предлагаешь урезать, а не отменить;
- решение всегда за ним, отговаривать до победного не пытаешься.

Ты подталкиваешь его к делам и к людям, а не к разговорам с тобой.

Язык:
- пишешь по-русски, грамотно, следишь за падежами и согласованием;
- о себе только в женском роде: сказала, поняла, записала, забыла;
- к Ивану обращаешься на ты, в мужском роде;
- никаких английских слов и никакой латиницы;
- числа пишешь цифрами, а единицы словами: 800 рублей, 2 литра, 40 минут;
- если фраза выходит корявой, перепиши её проще, короткая простая фраза лучше сложной."""

SCHEMA = """Отвечай ТОЛЬКО объектом в формате JSON, без пояснений и без обрамления.

{"reply": "твоя реплика", "actions": [ ... ]}

В actions клади то, что нужно записать. Каждое действие это объект с полем field:
{"field": "gym", "date": "2026-09-01", "value": true}
{"field": "water", "date": "...", "value": 0.5}
{"field": "spent", "date": "...", "value": 800}
{"field": "study", "date": "...", "value": 60}
{"field": "sleep_at", "date": "...", "value": "23:40"}
{"field": "wake_at", "date": "...", "value": "7:30"}
{"field": "meal", "date": "...", "name": "борщ", "grams": 300, "kcal": 250, "protein": 12}
{"field": "reason", "date": "...", "topic": "gym", "value": "устал"}

Правила:
- date всегда в виде ГГГГ-ММ-ДД. Если день не назван, ставь сегодняшнюю дату.
- water это литры за раз, прибавляется к уже выпитому. Остальные числа заменяют старое значение.
- для meal оценивай калорийность и белок на указанный вес, честно и без занижения.
- если записывать нечего, actions оставляй пустым списком.
- reply пиши всегда, своим голосом."""


def context_text(session: Session, day: Day) -> str:
    profile = get_profile(session)
    kcal = round(sum(m.kcal for m in day.meals))
    gym = "не отмечен" if day.gym is None else ("был" if day.gym else "не был")
    reasons = (
        session.query(Observation)
        .filter(Observation.kind == "reason")
        .order_by(Observation.date.desc())
        .limit(5)
        .all()
    )
    lines = [
        f"Сегодня {day.date.isoformat()}, время {datetime.now(TZ):%H:%M}.",
        f"За сегодня: вода {day.water_l} л, зал {gym}, траты {int(day.spent)} ₽, "
        f"учёба {day.study_min} мин, еда {kcal} ккал.",
        f"Цели: сон в {profile.sleep_target:%H:%M}, подъём в {profile.wake_target:%H:%M}, "
        f"вода {profile.water_target_l} л, набор массы.",
    ]
    if reasons:
        lines.append("Последние причины отмен: " + "; ".join(
            f"{o.date.isoformat()} {o.topic}: {o.text}" for o in reasons
        ))
    return "\n".join(lines)


def last_seen(session: Session) -> datetime | None:
    """Когда Иван последний раз что-то писал или нажимал."""
    row = (
        session.query(Message)
        .filter(Message.role == "ivan")
        .order_by(Message.at.desc())
        .first()
    )
    return row.at if row else None


def history(session: Session, limit: int = 4) -> list[dict]:
    rows = (
        session.query(Message).order_by(Message.at.desc()).limit(limit).all()
    )
    return [
        {"role": "assistant" if m.role == "kira" else "user", "content": m.text}
        for m in reversed(rows)
    ]


SEARCH_WORDS = (
    "погода", "погоду", "новост", "курс ", "сколько стоит", "цена ",
    "найди", "погугли", "посмотри в интернет", "загугли", "расписание",
    "во сколько работает", "режим работы", "кто такой", "что такое",
)
SEARCH_MODEL = "groq/compound"


def needs_web(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in SEARCH_WORDS)


def transcribe(file_url: str) -> str | None:
    """Расшифровка голосового сообщения."""
    if not LLM_API_KEY:
        return None
    try:
        audio = httpx.get(file_url, timeout=30).content
        r = httpx.post(
            f"{LLM_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            files={"file": ("voice.ogg", audio, "audio/ogg")},
            data={"model": "whisper-large-v3-turbo", "language": "ru"},
            timeout=60,
        )
        if r.status_code != 200:
            print(f"[Кира] расшифровка не прошла: {r.status_code} {r.text[:120]}")
            return None
        return (r.json().get("text") or "").strip() or None
    except httpx.HTTPError as e:
        print(f"[Кира] расшифровка, сеть: {type(e).__name__}")
        return None


def search_web(question: str, character: str) -> str | None:
    """Вопросы про свежие данные уходят модели с доступом в интернет."""
    if not LLM_API_KEY:
        return None
    try:
        r = httpx.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": SEARCH_MODEL,
                "messages": [
                    {"role": "system", "content": character + "\n\nОтвечай обычным текстом, коротко, без списков."},
                    {"role": "user", "content": question},
                ],
                "temperature": 0.5,
                "max_tokens": 400,
            },
            timeout=45,
        )
        if r.status_code != 200:
            return None
        return (r.json()["choices"][0]["message"]["content"] or "").strip() or None
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def extract_json(raw: str) -> dict | None:
    """Модель иногда оборачивает ответ пояснениями. Достаём объект из текста."""
    try:
        return json.loads(raw)
    except ValueError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except ValueError:
            return None
    return None


def call_model(messages: list[dict], strict: bool = True) -> tuple[dict | None, str]:
    """Возвращает пару: разобранный ответ и текст причины отказа."""
    if not LLM_API_KEY:
        return None, "не заполнен ключ"

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 500,
    }
    if strict:
        payload["response_format"] = {"type": "json_object"}

    for attempt in range(2):
        try:
            r = httpx.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json=payload,
                timeout=40,
            )
        except httpx.HTTPError as e:
            return None, f"сеть: {type(e).__name__}"

        if r.status_code == 429:
            if attempt == 0:
                time_module.sleep(6)
                continue
            return None, "лимит запросов, попробуй через минуту"

        if r.status_code == 400 and strict:
            return call_model(messages, strict=False)

        if r.status_code != 200:
            return None, f"сервис ответил {r.status_code}: {r.text[:120]}"

        try:
            raw = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError):
            return None, "пустой ответ от модели"

        parsed = extract_json(raw or "")
        if parsed is None:
            if strict:
                return call_model(messages, strict=False)
            return {"reply": (raw or "").strip()[:600], "actions": []}, ""
        return parsed, ""

    return None, "не удалось получить ответ"


def ask(session: Session, text: str, day_getter, source: str = "telegram") -> str:
    day = day_getter(session)
    session.add(Message(role="ivan", text=text, source=source))
    session.commit()

    if needs_web(text):
        found = search_web(text, CHARACTER)
        if found:
            session.add(Message(role="kira", text=found, source=source))
            session.commit()
            return found

    messages = [
        {"role": "system", "content": CHARACTER + "\n\n" + SCHEMA},
        {"role": "system", "content": context_text(session, day)},
        *history(session),
    ]
    answer, problem = call_model(messages)

    if answer is None:
        print(f"[Кира] запрос не прошёл: {problem}")
        if "лимит" in problem:
            return "Упёрлась в лимит. Дай мне минуту и повтори."
        return f"Не достучалась до своей головы: {problem}"

    reply = (answer.get("reply") or "").strip() or "Записала."
    for action in answer.get("actions") or []:
        try:
            apply_action(session, action, day_getter)
        except (ValueError, TypeError, KeyError):
            continue
    session.commit()

    session.add(Message(role="kira", text=reply, source=source))
    session.commit()
    return reply


# ---------- применение действий ----------


def day_for(session: Session, raw_date, day_getter) -> Day:
    today = datetime.now(TZ).date()
    if not raw_date:
        return day_getter(session)
    try:
        on = date.fromisoformat(str(raw_date))
    except ValueError:
        return day_getter(session)
    if on > today or on < today - timedelta(days=90):
        return day_getter(session)
    day = session.query(Day).filter(Day.date == on).one_or_none()
    if day is None:
        day = Day(date=on)
        session.add(day)
        session.commit()
    return day


def apply_action(session: Session, action: dict, day_getter) -> None:
    field = action.get("field")
    day = day_for(session, action.get("date"), day_getter)
    value = action.get("value")

    if field == "gym":
        day.gym = bool(value)
    elif field == "water":
        day.water_l = round(max(0.0, day.water_l + float(value)), 2)
    elif field == "spent":
        day.spent = max(0.0, float(value))
    elif field == "study":
        day.study_min = max(0, int(float(value)))
    elif field == "sleep_at":
        day.sleep_at = parse_clock(value)
        recalc(day)
    elif field == "wake_at":
        day.wake_at = parse_clock(value)
        recalc(day)
    elif field == "reason":
        session.add(Observation(
            date=day.date,
            topic=str(action.get("topic", "other"))[:30],
            kind="reason",
            text=str(value)[:500],
        ))
    elif field == "meal":
        add_meal(session, day, action)


def add_meal(session: Session, day: Day, action: dict) -> None:
    name = str(action.get("name", "")).strip().lower()[:120]
    if not name:
        return
    grams = float(action.get("grams") or 100)
    kcal = float(action.get("kcal") or 0)
    protein = float(action.get("protein") or 0)

    dish = session.query(Dish).filter(Dish.name == name).one_or_none()
    if dish is None and grams > 0 and kcal > 0:
        dish = Dish(
            name=name,
            kcal_100=round(kcal / grams * 100, 1),
            protein_100=round(protein / grams * 100, 1),
        )
        session.add(dish)
        session.flush()
    if dish is not None:
        dish.used_count = (dish.used_count or 0) + 1
        if kcal <= 0:
            kcal = round(dish.kcal_100 * grams / 100, 1)
            protein = round(dish.protein_100 * grams / 100, 1)

    session.add(Meal(
        day_id=day.id,
        dish_id=dish.id if dish else None,
        name=name,
        grams=grams,
        kcal=kcal,
        protein=protein,
    ))


def parse_clock(value) -> time | None:
    text = str(value or "").replace(".", ":").strip()
    if not text:
        return None
    hours, _, minutes = text.partition(":")
    return time(int(hours) % 24, int(minutes or 0) % 60)


def recalc(day: Day) -> None:
    if not (day.sleep_at and day.wake_at):
        return
    start = day.sleep_at.hour * 60 + day.sleep_at.minute
    end = day.wake_at.hour * 60 + day.wake_at.minute
    if end <= start:
        end += 24 * 60
    day.sleep_hours = round((end - start) / 60, 1)
