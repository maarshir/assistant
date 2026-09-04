from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Profile(Base):
    """Единственная строка: параметры Ивана и цели."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    age: Mapped[int | None] = mapped_column(Integer)
    activity: Mapped[str] = mapped_column(String(20), default="medium")
    body_goal: Mapped[str] = mapped_column(String(20), default="gain")

    calorie_target: Mapped[int | None] = mapped_column(Integer)
    protein_target: Mapped[int | None] = mapped_column(Integer)
    water_target_l: Mapped[float] = mapped_column(Float, default=2.5)

    sleep_target: Mapped[time] = mapped_column(Time, default=time(23, 30))
    wake_target: Mapped[time] = mapped_column(Time, default=time(7, 30))
    evening_check_at: Mapped[time] = mapped_column(Time, default=time(22, 0))

    gym_days: Mapped[str] = mapped_column(String(20), default="1,3,5")
    tone_level: Mapped[int] = mapped_column(Integer, default=2)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Day(Base):
    """Одна запись на дату. Сюда стекаются все отметки дня."""

    __tablename__ = "day"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)

    sleep_at: Mapped[time | None] = mapped_column(Time)
    wake_at: Mapped[time | None] = mapped_column(Time)
    sleep_hours: Mapped[float | None] = mapped_column(Float)

    gym: Mapped[bool | None] = mapped_column(Boolean)
    gym_note: Mapped[str | None] = mapped_column(String(200))

    water_l: Mapped[float] = mapped_column(Float, default=0)
    spent: Mapped[float] = mapped_column(Float, default=0)
    study_min: Mapped[int] = mapped_column(Integer, default=0)

    note: Mapped[str | None] = mapped_column(Text)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)

    meals: Mapped[list["Meal"]] = relationship(back_populates="day")


class Dish(Base):
    """Кэш расчётов. Одно и то же блюдо считается моделью только раз."""

    __tablename__ = "dish"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    kcal_100: Mapped[float] = mapped_column(Float)
    protein_100: Mapped[float] = mapped_column(Float, default=0)
    fat_100: Mapped[float] = mapped_column(Float, default=0)
    carb_100: Mapped[float] = mapped_column(Float, default=0)
    composition: Mapped[str | None] = mapped_column(Text)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Meal(Base):
    __tablename__ = "meal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("day.id"), index=True)
    dish_id: Mapped[int | None] = mapped_column(ForeignKey("dish.id"))

    name: Mapped[str] = mapped_column(String(120))
    grams: Mapped[float] = mapped_column(Float, default=100)
    kcal: Mapped[float] = mapped_column(Float, default=0)
    protein: Mapped[float] = mapped_column(Float, default=0)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    day: Mapped["Day"] = relationship(back_populates="meals")


class Task(Base):
    __tablename__ = "task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String(300))
    due: Mapped[date | None] = mapped_column(Date, index=True)
    due_time: Mapped[time | None] = mapped_column(Time)
    repeat: Mapped[str | None] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(Integer, default=1)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Expense(Base):
    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(String(200))


class Habit(Base):
    __tablename__ = "habit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="check")
    target: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class HabitMark(Base):
    __tablename__ = "habit_mark"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habit.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float, default=1)


class Message(Base):
    """Общая история диалога для сайта и бота."""

    __tablename__ = "message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="web")
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Observation(Base):
    """Причины отмен и замеченные закономерности. Основа для возражений."""

    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    topic: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(20), default="reason")
    text: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer, default=1)


class BotState(Base):
    """Состояние пошагового разговора с ботом."""

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    step: Mapped[str | None] = mapped_column(String(30))
    awaiting: Mapped[str | None] = mapped_column(String(30))
    queue: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReminderLog(Base):
    """Что уже отправлено сегодня, чтобы не повторяться."""

    __tablename__ = "reminder_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
