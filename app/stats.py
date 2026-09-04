"""Сводки для экранов статистики. Только чтение, ничего не меняет."""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Day, Dish, Meal, Profile
from app.db import get_profile

WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_OF = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def day_rows(session: Session, since: date, until: date) -> list[dict]:
    days = {
        d.date: d
        for d in session.query(Day)
        .filter(Day.date >= since, Day.date <= until)
        .all()
    }
    kcal_by_day = {}
    for day in days.values():
        kcal_by_day[day.date] = round(sum(m.kcal for m in day.meals))

    rows = []
    step = until
    while step >= since:
        day = days.get(step)
        rows.append({
            "date": step,
            "label": f"{WEEKDAYS_SHORT[step.weekday()]} {step.day}",
            "sleep": day.sleep_hours if day else None,
            "gym": day.gym if day else None,
            "water": day.water_l if day else 0,
            "kcal": kcal_by_day.get(step, 0),
            "spent": day.spent if day else 0,
            "study": day.study_min if day else 0,
            "empty": day is None,
        })
        step -= timedelta(days=1)
    return rows


def average(values: list) -> float | None:
    real = [v for v in values if v]
    if not real:
        return None
    return round(sum(real) / len(real), 1)


def summarize(rows: list[dict]) -> dict:
    return {
        "sleep": average([r["sleep"] for r in rows]),
        "gym": sum(1 for r in rows if r["gym"]),
        "water": average([r["water"] for r in rows]),
        "kcal": average([r["kcal"] for r in rows]),
        "spent": round(sum(r["spent"] for r in rows)),
        "study": round(sum(r["study"] for r in rows)),
        "days": len(rows),
    }


def week(session: Session, today: date) -> dict:
    rows = day_rows(session, today - timedelta(days=6), today)
    return {"rows": rows, "total": summarize(rows), "streak": gym_streak(rows)}


def month(session: Session, today: date) -> dict:
    first = today.replace(day=1)
    rows = day_rows(session, first, today)
    total = summarize(rows)
    return {
        "rows": rows,
        "total": total,
        "title": f"{MONTHS_OF[today.month - 1]}",
        "late_nights": sum(1 for r in rows if r["sleep"] and r["sleep"] < 6),
        "best": best_day(rows),
    }


def gym_streak(rows: list[dict]) -> int:
    """Сколько дней подряд без зала, считая от последнего дня."""
    count = 0
    for row in rows:
        if row["gym"]:
            break
        if row["gym"] is False:
            count += 1
    return count


def best_day(rows: list[dict]) -> dict | None:
    scored = [r for r in rows if r["sleep"] or r["gym"]]
    if not scored:
        return None
    return max(scored, key=lambda r: (r["gym"] is True, r["sleep"] or 0))


def food(session: Session, today: date, days_back: int = 7) -> dict:
    since = today - timedelta(days=days_back - 1)
    meals = (
        session.query(Meal)
        .join(Day, Meal.day_id == Day.id)
        .filter(Day.date >= since)
        .order_by(Meal.at.desc())
        .all()
    )
    by_day: dict[date, list] = {}
    for meal in meals:
        day = session.get(Day, meal.day_id)
        by_day.setdefault(day.date, []).append(meal)

    groups = []
    for on in sorted(by_day, reverse=True):
        items = by_day[on]
        groups.append({
            "date": on,
            "label": f"{on.day} {MONTHS_OF[on.month - 1]}",
            "kcal": round(sum(m.kcal for m in items)),
            "protein": round(sum(m.protein for m in items)),
            "meals": items,
        })

    dishes = (
        session.query(Dish).order_by(Dish.used_count.desc()).limit(20).all()
    )
    profile = get_profile(session)
    return {"groups": groups, "dishes": dishes, "profile": profile}
