from __future__ import annotations

from datetime import date, timedelta

import aiosqlite

from app.db.database import Database, utc_now_iso
from app.db.models import ParsedScheduleItem, ScheduleEvent


class ScheduleService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add_event(
        self,
        user_id: int,
        event_date: str,
        start_time: str,
        title: str,
        *,
        end_time: str = "",
        location: str = "",
        notes: str = "",
        source: str = "manual",
    ) -> ScheduleEvent:
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO schedule_events (
                    user_id, event_date, start_time, end_time,
                    title, location, notes, source, is_done, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    user_id,
                    event_date,
                    start_time.strip(),
                    end_time.strip(),
                    title.strip(),
                    location.strip(),
                    notes.strip(),
                    source,
                    now,
                ),
            )
            event_id = cursor.lastrowid
            await conn.commit()
            row_cur = await conn.execute(
                "SELECT * FROM schedule_events WHERE id = ?", (event_id,)
            )
            row = await row_cur.fetchone()
            assert row is not None
            return self._row_to_event(row)

    async def import_parsed_events(
        self,
        user_id: int,
        items: list[ParsedScheduleItem],
        *,
        source: str,
        replace_dates: bool = True,
    ) -> int:
        if not items:
            return 0
        now = utc_now_iso()
        unique_dates = sorted({item.event_date for item in items})
        async with self.db.connect() as conn:
            if replace_dates and unique_dates:
                placeholders = ",".join("?" for _ in unique_dates)
                await conn.execute(
                    f"""
                    DELETE FROM schedule_events
                    WHERE user_id = ? AND event_date IN ({placeholders})
                    """,
                    [user_id, *unique_dates],
                )
            for item in items:
                await conn.execute(
                    """
                    INSERT INTO schedule_events (
                        user_id, event_date, start_time, end_time,
                        title, location, notes, source, is_done, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        user_id,
                        item.event_date,
                        item.start_time.strip(),
                        item.end_time.strip(),
                        item.title.strip(),
                        item.location.strip(),
                        item.notes.strip(),
                        source,
                        now,
                    ),
                )
            await conn.commit()
        return len(items)

    async def list_events_for_date(self, user_id: int, day_iso: str) -> list[ScheduleEvent]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE user_id = ? AND event_date = ?
                ORDER BY start_time ASC, id ASC
                """,
                (user_id, day_iso),
            )
            rows = await cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    async def list_events_in_range(
        self, user_id: int, start_iso: str, end_iso: str
    ) -> list[ScheduleEvent]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE user_id = ? AND event_date >= ? AND event_date <= ?
                ORDER BY event_date ASC, start_time ASC, id ASC
                """,
                (user_id, start_iso, end_iso),
            )
            rows = await cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    async def list_week_events(self, user_id: int, anchor_iso: str) -> tuple[str, str, list[ScheduleEvent]]:
        anchor = date.fromisoformat(anchor_iso)
        monday = anchor - timedelta(days=anchor.weekday())
        sunday = monday + timedelta(days=6)
        events = await self.list_events_in_range(user_id, monday.isoformat(), sunday.isoformat())
        return monday.isoformat(), sunday.isoformat(), events

    async def toggle_done(self, user_id: int, event_id: int) -> ScheduleEvent | None:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                "SELECT * FROM schedule_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )
            row = await cur.fetchone()
            if not row:
                return None
            new_val = 0 if row["is_done"] else 1
            await conn.execute(
                "UPDATE schedule_events SET is_done = ? WHERE id = ?",
                (new_val, event_id),
            )
            await conn.commit()
            updated_cur = await conn.execute(
                "SELECT * FROM schedule_events WHERE id = ?", (event_id,)
            )
            updated = await updated_cur.fetchone()
            return self._row_to_event(updated) if updated else None

    async def delete_event(self, user_id: int, event_id: int) -> bool:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                "DELETE FROM schedule_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def clear_week(self, user_id: int, start_iso: str, end_iso: str) -> int:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                DELETE FROM schedule_events
                WHERE user_id = ? AND event_date >= ? AND event_date <= ?
                """,
                (user_id, start_iso, end_iso),
            )
            await conn.commit()
            return cur.rowcount

    @staticmethod
    def _row_to_event(row: aiosqlite.Row) -> ScheduleEvent:
        return ScheduleEvent(
            id=row["id"],
            user_id=row["user_id"],
            event_date=row["event_date"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            title=row["title"],
            location=row["location"],
            notes=row["notes"],
            source=row["source"],
            is_done=bool(row["is_done"]),
            created_at=row["created_at"],
        )
