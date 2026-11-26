from __future__ import annotations

from datetime import date, timedelta

import aiosqlite

from app.db.database import Database, utc_now_iso
from app.db.models import FreeWindow, ParsedScheduleItem, ScheduleEvent


def _hhmm_to_min(hhmm: str) -> int | None:
    parts = hhmm.strip().split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        return None
    h, m = int(parts[0]), int(parts[1])
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h * 60 + m
    return None


def _min_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def compute_free_windows(
    events: list[ScheduleEvent],
    *,
    day_start: str = "08:00",
    day_end: str = "22:00",
    min_minutes: int = 45,
) -> list[FreeWindow]:
    """Finds free time slots between scheduled classes/events on a day."""
    start_m = _hhmm_to_min(day_start) or 480
    end_m = _hhmm_to_min(day_end) or 1320
    intervals: list[tuple[int, int]] = []
    for ev in events:
        s = _hhmm_to_min(ev.start_time)
        if s is None:
            continue
        e = _hhmm_to_min(ev.end_time) if ev.end_time else (s + 90)
        if e is None or e <= s:
            e = s + 90
        intervals.append((max(start_m, s), min(end_m, e)))

    if not intervals:
        return [FreeWindow(day_start, day_end, end_m - start_m)]

    intervals.sort()
    merged: list[tuple[int, int]] = []
    for s, e in intervals:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    windows: list[FreeWindow] = []
    cursor = start_m
    for s, e in merged:
        if s - cursor >= min_minutes:
            windows.append(FreeWindow(_min_to_hhmm(cursor), _min_to_hhmm(s), s - cursor))
        cursor = max(cursor, e)
    if end_m - cursor >= min_minutes:
        windows.append(FreeWindow(_min_to_hhmm(cursor), _min_to_hhmm(end_m), end_m - cursor))
    return windows


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
        meeting_info: str = "",
        source: str = "manual",
    ) -> ScheduleEvent:
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO schedule_events (
                    user_id, event_date, start_time, end_time,
                    title, location, notes, meeting_info, source, is_done, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    user_id,
                    event_date,
                    start_time.strip(),
                    end_time.strip(),
                    title.strip(),
                    location.strip(),
                    notes.strip(),
                    meeting_info.strip(),
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
                        title, location, notes, meeting_info, source, is_done, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        user_id,
                        item.event_date,
                        item.start_time.strip(),
                        item.end_time.strip(),
                        item.title.strip(),
                        item.location.strip(),
                        item.notes.strip(),
                        item.meeting_info.strip(),
                        source,
                        now,
                    ),
                )
            await conn.commit()
        return len(items)

    # --- Shared Group Schedules ---

    async def publish_shared_schedule(
        self, group_code: str, items: list[ParsedScheduleItem], uploaded_by: int
    ) -> int:
        code = group_code.strip().upper()
        if not code or not items:
            return 0
        now = utc_now_iso()
        unique_dates = sorted({item.event_date for item in items})
        async with self.db.connect() as conn:
            placeholders = ",".join("?" for _ in unique_dates)
            await conn.execute(
                f"DELETE FROM shared_schedules WHERE group_code = ? AND event_date IN ({placeholders})",
                [code, *unique_dates],
            )
            for item in items:
                await conn.execute(
                    """
                    INSERT INTO shared_schedules (
                        group_code, event_date, start_time, end_time,
                        title, location, notes, meeting_info, uploaded_by, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        item.event_date,
                        item.start_time.strip(),
                        item.end_time.strip(),
                        item.title.strip(),
                        item.location.strip(),
                        item.notes.strip(),
                        item.meeting_info.strip(),
                        uploaded_by,
                        now,
                    ),
                )
            await conn.commit()
        return len(items)

    async def sync_from_shared_group(
        self, user_id: int, group_code: str, *, from_date_iso: str
    ) -> int:
        code = group_code.strip().upper()
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM shared_schedules
                WHERE group_code = ? AND event_date >= ?
                ORDER BY event_date ASC, start_time ASC
                """,
                (code, from_date_iso),
            )
            rows = await cur.fetchall()
        if not rows:
            return 0
        items = [
            ParsedScheduleItem(
                event_date=r["event_date"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                title=r["title"],
                location=r["location"],
                notes=r["notes"],
                meeting_info=r["meeting_info"],
                group_tag=code,
            )
            for r in rows
        ]
        return await self.import_parsed_events(user_id, items, source="shared", replace_dates=True)

    async def list_shared_groups(self, from_date_iso: str) -> list[str]:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                "SELECT DISTINCT group_code FROM shared_schedules WHERE event_date >= ? ORDER BY group_code ASC",
                (from_date_iso,),
            )
            return [r["group_code"] for r in await cur.fetchall()]

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
        keys = set(row.keys())
        return ScheduleEvent(
            id=row["id"],
            user_id=row["user_id"],
            event_date=row["event_date"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            title=row["title"],
            location=row["location"],
            notes=row["notes"],
            meeting_info=row["meeting_info"] if "meeting_info" in keys else "",
            source=row["source"],
            is_done=bool(row["is_done"]),
            created_at=row["created_at"],
        )
