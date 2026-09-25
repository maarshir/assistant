import os
from datetime import date, datetime, time

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from app.config import (
    APP_PASSWORD,
    SECRET_KEY,
    TELEGRAM_CHAT_ID,
    TELEGRAM_TOKEN,
    TELEGRAM_WEBHOOK_SECRET,
    TZ,
)
from app.db import get_profile, get_session, init_db
from app.models import Day, Profile
from app import bot as botlogic
from app import reminders
from app import security
from app import stats

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI(title="Ассистент")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def css_version() -> str:
    """Метка версии стилей, чтобы браузер не показывал старое оформление."""
    try:
        return str(int(os.path.getmtime(os.path.join(STATIC_DIR, "app.css"))))
    except OSError:
        return "1"


templates.env.globals["css_version"] = css_version()

signer = URLSafeSerializer(SECRET_KEY, salt="auth")
COOKIE = "assistant_session"


def is_logged_in(request: Request) -> bool:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return False
    try:
        return signer.loads(raw) == "ok"
    except BadSignature:
        return False


def today_date() -> date:
    return datetime.now(TZ).date()


def get_day(session: Session, on: date | None = None) -> Day:
    on = on or today_date()
    day = session.query(Day).filter(Day.date == on).one_or_none()
    if day is None:
        day = Day(date=on)
        session.add(day)
        session.commit()
    return day


@app.on_event("startup")
def startup():
    init_db()


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
def login(password: str = Form(...)):
    if password != APP_PASSWORD:
        return RedirectResponse("/login?error=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE,
        signer.dumps("ok"),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/api/tg-auth")
async def tg_auth(request: Request):
    """Вход из окна внутри Телеграма: проверяем подпись и что это владелец."""
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "no data"}, status_code=400)
    init_data = body.get("init_data", "") if isinstance(body, dict) else ""
    if not init_data or not TELEGRAM_TOKEN:
        return JSONResponse({"error": "no data"}, status_code=400)

    fields = security.check_init_data(init_data, TELEGRAM_TOKEN)
    if fields is None:
        return JSONResponse({"error": "bad signature"}, status_code=403)

    # Подпись доказывает только, что данные пришли от Телеграма.
    # Открыть окно бота может кто угодно, поэтому сверяем номер с владельцем.
    if not security.same_id(security.init_data_user_id(fields), TELEGRAM_CHAT_ID):
        return JSONResponse({"error": "not owner"}, status_code=403)

    response = JSONResponse({"ok": True})
    response.set_cookie(
        COOKIE,
        signer.dumps("ok"),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="none",
        secure=True,
    )
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def today(request: Request, session: Session = Depends(get_session)):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    day = get_day(session)
    profile = get_profile(session)
    kcal = sum(m.kcal for m in day.meals)
    target = profile.calorie_target or 2500
    kcal_ratio = round(min(1.0, kcal / target) * 251, 1)
    week_rows = list(reversed(stats.week(session, today_date())["rows"]))

    return templates.TemplateResponse(
        request,
        "today.html",
        {
            "day": day,
            "profile": profile,
            "kcal": round(kcal),
            "protein": round(sum(m.protein for m in day.meals)),
            "kcal_ratio": kcal_ratio,
            "week_rows": week_rows,
            "path": "/",
            "date_label": format_date(day.date),
        },
    )


MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
WEEKDAYS = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


def format_date(on: date) -> str:
    return f"{WEEKDAYS[on.weekday()]}, {on.day} {MONTHS[on.month - 1]}"


@app.post("/api/mark")
def mark(
    request: Request,
    field: str = Form(...),
    value: str = Form(""),
    session: Session = Depends(get_session),
):
    """Обновляет одну отметку текущего дня и возвращает свежие значения."""
    if not is_logged_in(request):
        return JSONResponse({"error": "auth"}, status_code=401)

    day = get_day(session)

    try:
        if field == "gym":
            day.gym = not bool(day.gym)
        elif field == "water":
            day.water_l = round(max(0.0, day.water_l + float(value or 0.25)), 2)
        elif field == "spent":
            day.spent = float(value or 0)
        elif field == "study":
            day.study_min = int(float(value or 0))
        elif field == "sleep_at":
            day.sleep_at = parse_time(value)
        elif field == "wake_at":
            day.wake_at = parse_time(value)
            recalc_sleep(day)
        elif field == "note":
            day.note = value.strip() or None
        else:
            return JSONResponse({"error": "unknown field"}, status_code=400)
    except ValueError:
        return JSONResponse({"error": "bad value"}, status_code=400)

    session.commit()

    return {
        "gym": day.gym,
        "water_l": day.water_l,
        "spent": day.spent,
        "study_min": day.study_min,
        "sleep_at": day.sleep_at.strftime("%H:%M") if day.sleep_at else None,
        "wake_at": day.wake_at.strftime("%H:%M") if day.wake_at else None,
        "sleep_hours": day.sleep_hours,
    }


def parse_time(value: str) -> time | None:
    value = value.strip()
    if not value:
        return None
    hours, _, minutes = value.partition(":")
    return time(int(hours), int(minutes or 0))


def recalc_sleep(day: Day) -> None:
    """Считает длительность сна с переходом через полночь."""
    if not (day.sleep_at and day.wake_at):
        return
    start = day.sleep_at.hour * 60 + day.sleep_at.minute
    end = day.wake_at.hour * 60 + day.wake_at.minute
    if end <= start:
        end += 24 * 60
    day.sleep_hours = round((end - start) / 60, 1)


@app.get("/week", response_class=HTMLResponse)
def week(request: Request, session: Session = Depends(get_session)):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    data = stats.week(session, today_date())
    return templates.TemplateResponse(request, "week.html", {"path": "/week", **data})


@app.get("/month", response_class=HTMLResponse)
def month(request: Request, session: Session = Depends(get_session)):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    data = stats.month(session, today_date())
    data["title_month"] = data.pop("title")
    return templates.TemplateResponse(request, "month.html", {"path": "/month", **data})


@app.get("/food", response_class=HTMLResponse)
def food(request: Request, session: Session = Depends(get_session)):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    data = stats.food(session, today_date())
    return templates.TemplateResponse(request, "food.html", {"path": "/food", **data})


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, session: Session = Depends(get_session)):
    """Сюда Телеграм присылает каждое сообщение и нажатие кнопки."""
    header = request.headers.get("x-telegram-bot-api-secret-token")
    if not security.webhook_secret_ok(header, TELEGRAM_WEBHOOK_SECRET):
        return JSONResponse({"error": "auth"}, status_code=401)
    update = await request.json()
    botlogic.handle_update(session, update, get_day)
    return {"ok": True}


@app.get("/api/tick")
def tick(request: Request, session: Session = Depends(get_session)):
    """Дёргается внешним планировщиком раз в несколько минут."""
    secret = os.getenv("CRON_SECRET", "")
    if secret:
        header = request.headers.get("authorization", "")
        if header != f"Bearer {secret}":
            return JSONResponse({"error": "auth"}, status_code=401)
    return {"sent": reminders.tick(session, get_day)}


@app.get("/api/health")
def health():
    return {"ok": True}
