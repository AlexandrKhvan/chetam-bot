from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAY_SHORT_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
WEEKDAY_FULL_RU = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
MONTH_GENITIVE_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def get_zoneinfo(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def user_now(tz_name: str) -> datetime:
    return datetime.now(get_zoneinfo(tz_name))


def user_today(tz_name: str) -> date:
    return user_now(tz_name).date()


def user_today_iso(tz_name: str) -> str:
    return user_today(tz_name).isoformat()


def user_tomorrow_iso(tz_name: str) -> str:
    return (user_today(tz_name) + timedelta(days=1)).isoformat()


def shift_date_iso(day_iso: str, delta_days: int) -> str:
    return (date.fromisoformat(day_iso) + timedelta(days=delta_days)).isoformat()


def format_date_ru(day_iso: str, today_iso: str | None = None) -> str:
    d = date.fromisoformat(day_iso)
    wd = WEEKDAY_SHORT_RU[d.weekday()]
    base = f"{wd}, {d.day} {MONTH_GENITIVE_RU[d.month]}"
    if today_iso:
        diff = (d - date.fromisoformat(today_iso)).days
        if diff == 0:
            return f"Сегодня · {base}"
        if diff == 1:
            return f"Завтра · {base}"
        if diff == -1:
            return f"Вчера · {base}"
    return base


def format_weekday_short_ru(day_iso: str) -> str:
    d = date.fromisoformat(day_iso)
    return f"{WEEKDAY_SHORT_RU[d.weekday()]} {d.day:02d}.{d.month:02d}"


def validate_hhmm(value: str) -> str | None:
    cleaned = value.strip().replace(".", ":")
    parts = cleaned.split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None
