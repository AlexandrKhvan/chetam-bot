from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import aiosqlite

from app.db.database import Database, utc_now_iso
from app.db.models import Reminder
from app.services.time_utils import format_date_ru, get_zoneinfo, user_now

RELATIVE_RE = re.compile(
    r"^(?:через|in)\s+(\d+)\s*(м|мин|минут[уы]?|ч|час(?:а|ов)?|д|дн(?:я|ей)?|день|min(?:s|utes?)?|h(?:r|rs|ours?)?|d(?:ays?)?)\b\s*(.*)$",
    re.IGNORECASE,
)
DAILY_RE = re.compile(
    r"^(?:каждый\s+день|ежедневно|every\s+day|daily)\s+(?:в\s+|at\s+)?(\d{1,2})[:.](\d{2})\s+(.*)$",
    re.IGNORECASE,
)
DAY_TIME_RE = re.compile(
    r"^(?:(сегодня|завтра|послезавтра|\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+)?(?:в\s+|at\s+)?(\d{1,2})[:.](\d{2})\s+(.*)$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ParsedReminder:
    remind_at_local: datetime
    remind_at_utc: datetime
    text: str
    repeat_rule: str = ""  # "" | "daily"


def parse_reminder_input(raw: str, tz_name: str, *, now_local: datetime | None = None) -> ParsedReminder | None:
    """Parses natural Russian/English reminder phrases:
    - 'через 30 мин выключить плиту'
    - 'через 2 часа сдать лабу'
    - 'в 19:30 позвонить маме'
    - 'завтра в 10:00 отправить отчёт'
    - '28.11 в 14:00 зачёт'
    - 'каждый день в 22:00 пить витамины'
    """
    cleaned = raw.strip()
    if not cleaned:
        return None

    tz = get_zoneinfo(tz_name)
    now = now_local or user_now(tz_name)

    # 1. Relative: "через 30 мин ..." / "через 2 часа ..."
    m_rel = RELATIVE_RE.match(cleaned)
    if m_rel:
        amount = int(m_rel.group(1))
        unit = m_rel.group(2).lower()
        body = m_rel.group(3).strip(" -–—:")
        if amount <= 0 or not body:
            return None
        if unit.startswith(("м", "min")):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("ч", "h")):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        target_local = (now + delta).replace(second=0, microsecond=0)
        return ParsedReminder(
            remind_at_local=target_local,
            remind_at_utc=target_local.astimezone(timezone.utc),
            text=body[0].upper() + body[1:],
            repeat_rule="",
        )

    # 2. Daily recurring: "каждый день в 22:00 ..."
    m_daily = DAILY_RE.match(cleaned)
    if m_daily:
        h, minute = int(m_daily.group(1)), int(m_daily.group(2))
        body = m_daily.group(3).strip(" -–—:")
        if not (0 <= h <= 23 and 0 <= minute <= 59 and body):
            return None
        target_local = now.replace(hour=h, minute=minute, second=0, microsecond=0)
        if target_local <= now:
            target_local += timedelta(days=1)
        return ParsedReminder(
            remind_at_local=target_local,
            remind_at_utc=target_local.astimezone(timezone.utc),
            text=body[0].upper() + body[1:],
            repeat_rule="daily",
        )

    # 3. Specific day + time or time today/tomorrow: "[завтра|28.11] в 19:30 ..."
    m_dt = DAY_TIME_RE.match(cleaned)
    if m_dt:
        day_token = (m_dt.group(1) or "").lower().strip()
        h, minute = int(m_dt.group(2)), int(m_dt.group(3))
        body = m_dt.group(4).strip(" -–—:")
        if not (0 <= h <= 23 and 0 <= minute <= 59 and body):
            return None

        target_date = now.date()
        if day_token == "завтра":
            target_date = now.date() + timedelta(days=1)
        elif day_token == "послезавтра":
            target_date = now.date() + timedelta(days=2)
        elif day_token and day_token != "сегодня":
            parts = day_token.split(".")
            d_val, mo_val = int(parts[0]), int(parts[1])
            y_val = int(parts[2]) + (2000 if len(parts) == 3 and int(parts[2]) < 100 else 0) if len(parts) == 3 else now.year
            try:
                target_date = date(y_val, mo_val, d_val)
            except ValueError:
                return None

        target_local = datetime(
            target_date.year, target_date.month, target_date.day, h, minute, tzinfo=tz
        )
        if not day_token and target_local <= now:
            target_local += timedelta(days=1)

        return ParsedReminder(
            remind_at_local=target_local,
            remind_at_utc=target_local.astimezone(timezone.utc),
            text=body[0].upper() + body[1:],
            repeat_rule="",
        )

    return None


def format_reminder_time_local(remind_at_utc: str, tz_name: str) -> str:
    dt_utc = datetime.fromisoformat(remind_at_utc)
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_local = dt_utc.astimezone(get_zoneinfo(tz_name))
    today_iso = user_now(tz_name).date().isoformat()
    day_label = format_date_ru(dt_local.date().isoformat(), today_iso)
    return f"{day_label}, {dt_local.strftime('%H:%M')}"


class ReminderService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_reminder(
        self,
        user_id: int,
        text: str,
        remind_at_utc: datetime,
        *,
        task_id: int | None = None,
        repeat_rule: str = "",
    ) -> Reminder:
        utc_dt = remind_at_utc.astimezone(timezone.utc).replace(microsecond=0)
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                INSERT INTO reminders (
                    user_id, task_id, text, remind_at_utc, repeat_rule, is_sent, created_at
                )
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (user_id, task_id, text.strip(), utc_dt.isoformat(), repeat_rule, now),
            )
            rem_id = cur.lastrowid
            await conn.commit()
            row_cur = await conn.execute("SELECT * FROM reminders WHERE id = ?", (rem_id,))
            row = await row_cur.fetchone()
            assert row is not None
            return self._row_to_reminder(row)

    async def get_reminder(self, user_id: int, reminder_id: int) -> Reminder | None:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                "SELECT * FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
            row = await cur.fetchone()
            return self._row_to_reminder(row) if row else None

    async def list_active(self, user_id: int) -> list[Reminder]:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM reminders
                WHERE user_id = ? AND is_sent = 0
                ORDER BY remind_at_utc ASC, id ASC
                """,
                (user_id,),
            )
            rows = await cur.fetchall()
            return [self._row_to_reminder(r) for r in rows]

    async def list_due(self, now_utc: datetime | None = None) -> list[Reminder]:
        cutoff = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM reminders
                WHERE is_sent = 0 AND remind_at_utc <= ?
                ORDER BY remind_at_utc ASC, id ASC
                """,
                (cutoff.isoformat(),),
            )
            rows = await cur.fetchall()
            return [self._row_to_reminder(r) for r in rows]

    async def mark_triggered(self, reminder_id: int) -> Reminder | None:
        """Marks one-shot reminder as sent, or advances a 'daily' reminder by +1 day."""
        async with self.db.connect() as conn:
            cur = await conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            row = await cur.fetchone()
            if not row:
                return None

            if row["repeat_rule"] == "daily":
                prev_dt = datetime.fromisoformat(row["remind_at_utc"])
                if prev_dt.tzinfo is None:
                    prev_dt = prev_dt.replace(tzinfo=timezone.utc)
                next_dt = prev_dt + timedelta(days=1)
                await conn.execute(
                    "UPDATE reminders SET remind_at_utc = ?, is_sent = 0 WHERE id = ?",
                    (next_dt.isoformat(), reminder_id),
                )
            else:
                await conn.execute(
                    "UPDATE reminders SET is_sent = 1 WHERE id = ?",
                    (reminder_id,),
                )
            await conn.commit()
            upd = await conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            u_row = await upd.fetchone()
            return self._row_to_reminder(u_row) if u_row else None

    async def snooze(
        self,
        user_id: int,
        reminder_id: int,
        *,
        minutes: int | None = None,
        target_utc: datetime | None = None,
    ) -> Reminder | None:
        existing = await self.get_reminder(user_id, reminder_id)
        if not existing:
            return None
        if target_utc is not None:
            new_dt = target_utc.astimezone(timezone.utc).replace(microsecond=0)
        else:
            new_dt = (datetime.now(timezone.utc) + timedelta(minutes=minutes or 15)).replace(
                second=0, microsecond=0
            )
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE reminders SET remind_at_utc = ?, is_sent = 0 WHERE id = ? AND user_id = ?",
                (new_dt.isoformat(), reminder_id, user_id),
            )
            await conn.commit()
            cur = await conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            row = await cur.fetchone()
            return self._row_to_reminder(row) if row else None

    async def delete_reminder(self, user_id: int, reminder_id: int) -> bool:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                "DELETE FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_reminder(row: aiosqlite.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            text=row["text"],
            remind_at_utc=row["remind_at_utc"],
            repeat_rule=row["repeat_rule"],
            is_sent=bool(row["is_sent"]),
            created_at=row["created_at"],
        )
