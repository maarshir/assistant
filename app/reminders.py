"""Вызывается раз в несколько минут. Решает, что пора отправить."""

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app import bot, brain
from app.config import TZ
from app.db import get_profile
from app.models import Day, Observation, Profile, ReminderLog

WATER_FROM = 10
WATER_TO = 21


def already_sent(session: Session, on: date, kind: str) -> bool:
    return (
        session.query(ReminderLog)
        .filter(ReminderLog.date == on, ReminderLog.kind == kind)
        .first()
        is not None
    )


def mark_sent(session: Session, on: date, kind: str) -> None:
    session.add(ReminderLog(date=on, kind=kind))
    session.commit()


def due(now: datetime, target: time, window_min: int = 20) -> bool:
    """Пора ли: целевое время прошло, но не больше окна назад."""
    target_dt = now.replace(
        hour=target.hour, minute=target.minute, second=0, microsecond=0
    )
    return timedelta(0) <= (now - target_dt) <= timedelta(minutes=window_min)


def tick(session: Session, day_getter) -> list[str]:
    """Возвращает список того, что отправил. Пустой список это норма."""
    now = datetime.now(TZ)
    today = now.date()
    day = day_getter(session)
    profile = get_profile(session)
    done = []

    # Иван только что писал сам, значит дёргать его лишний раз незачем
    seen = brain.last_seen(session)
    just_talked = bool(seen and (datetime.utcnow() - seen) < timedelta(minutes=20))

    # Подъём. Приветствие живое, без кнопок, любой ответ означает подъём.
    if due(now, profile.wake_target) and not day.wake_at:
        if not already_sent(session, today, "morning") and not just_talked:
            bot.send_morning(session)
            mark_sent(session, today, "morning")
            done.append("morning")

    # Проспал: два часа тишины после целевого подъёма
    late_at = (
        datetime.combine(today, profile.wake_target) + timedelta(hours=2)
    ).time()
    if due(now, late_at) and not day.wake_at and not just_talked:
        if not already_sent(session, today, "morning_late"):
            bot.send_morning(session, late=True)
            mark_sent(session, today, "morning_late")
            done.append("morning_late")

    # Вода, раз в час в своём окне
    if WATER_FROM <= now.hour <= WATER_TO and now.minute < 20:
        kind = f"water_{now.hour}"
        target = profile.water_target_l or 2.5
        if day.water_l < target and not already_sent(session, today, kind) and not just_talked:
            bot.send_water(session, day)
            mark_sent(session, today, kind)
            done.append(kind)

    # Зал в тренировочные дни
    gym_days = {int(d) for d in (profile.gym_days or "").split(",") if d.strip()}
    if now.weekday() + 1 in gym_days and day.gym is None:
        if due(now, time(18, 0)) and not already_sent(session, today, "gym"):
            bot.ask(session, day, "gym")
            mark_sent(session, today, "gym")
            done.append("gym")

    # Вечерний опрос
    if due(now, profile.evening_check_at) and not already_sent(session, today, "evening"):
        bot.start_evening(session, day)
        mark_sent(session, today, "evening")
        done.append("evening")

    # Отбой, за полчаса
    bed = profile.sleep_target
    bed_warn = (
        datetime.combine(today, bed) - timedelta(minutes=30)
    ).time()
    if due(now, bed_warn) and not already_sent(session, today, "bedtime"):
        bot.send_bedtime(session, profile)
        mark_sent(session, today, "bedtime")
        done.append("bedtime")

    # Спокойная эскалация: замечает закономерность, но не читает нотации
    if due(now, time(21, 0)) and not already_sent(session, today, "pattern"):
        note = find_pattern(session, today)
        if note:
            bot.tg.send(note)
            mark_sent(session, today, "pattern")
            done.append("pattern")

    return done


def find_pattern(session: Session, today: date) -> str | None:
    """Раз в неделю, не чаще: сообщает о замеченном, без давления."""
    week_ago = today - timedelta(days=6)
    recent = (
        session.query(ReminderLog)
        .filter(ReminderLog.kind == "pattern", ReminderLog.date >= week_ago)
        .first()
    )
    if recent:
        return None

    days = (
        session.query(Day)
        .filter(Day.date >= week_ago, Day.date <= today)
        .all()
    )
    if len(days) < 4:
        return None

    short = [d for d in days if d.sleep_hours and d.sleep_hours < 6]
    if len(short) >= 3:
        return (
            f"Слушай, за неделю {len(short)} ночи меньше шести часов. "
            "Не ругаюсь, просто говорю, что вижу. Сдвинем отбой на полчаса?"
        )

    skipped = [d for d in days if d.gym is False]
    if len(skipped) >= 3:
        return (
            "Зал пропущен три раза за неделю. Может, дело не в лени, "
            "а в том, что план слишком плотный? Урежем до двух раз?"
        )

    return None
