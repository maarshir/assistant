"""Первичная настройка базы. Запускать один раз: python setup_db.py"""

from app.db import SessionLocal, init_db
from app.models import Habit, Profile

DEFAULT_HABITS = [
    ("Вода", "number", 2.5),
    ("Зал", "check", None),
    ("Учёба", "number", 60),
    ("Без вредной еды", "check", None),
]


def main():
    init_db()
    print("Таблицы созданы.")

    with SessionLocal() as s:
        if not s.get(Profile, 1):
            s.add(Profile(id=1))
            print("Профиль создан, параметры заполнишь при первом запуске.")

        existing = {h.name for h in s.query(Habit).all()}
        for name, kind, target in DEFAULT_HABITS:
            if name not in existing:
                s.add(Habit(name=name, kind=kind, target=target))
                print(f"Привычка добавлена: {name}")

        s.commit()

    print("Готово.")


if __name__ == "__main__":
    main()
