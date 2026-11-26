from __future__ import annotations

import aiosqlite

from app.db.database import Database, utc_now_iso
from app.db.models import DayPlan, ScheduleEvent, Task


class TaskService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_task(
        self,
        user_id: int,
        title: str,
        *,
        notes: str = "",
        planned_date: str | None = None,
        planned_time: str | None = None,
        priority: int = 2,
        initial_status: str = "inbox",
    ) -> Task:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Task title cannot be empty")
        status = "planned" if planned_date else ("pool" if initial_status == "pool" else "inbox")
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO tasks (
                    user_id, title, notes, status, priority,
                    planned_date, planned_time, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    clean_title,
                    notes.strip(),
                    status,
                    priority,
                    planned_date,
                    planned_time,
                    now,
                ),
            )
            task_id = cursor.lastrowid
            await conn.commit()
            row_cur = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = await row_cur.fetchone()
            assert row is not None
            return self._row_to_task(row)

    async def create_many_inbox(self, user_id: int, titles: list[str]) -> list[Task]:
        created: list[Task] = []
        for raw in titles:
            cleaned = raw.strip().lstrip("-•*—– ").strip()
            if cleaned:
                created.append(await self.create_task(user_id, cleaned))
        return created

    async def get_task(self, user_id: int, task_id: int) -> Task | None:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cursor.fetchone()
            return self._row_to_task(row) if row else None

    async def list_inbox(self, user_id: int) -> list[Task]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'inbox'
                ORDER BY priority ASC, id DESC
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_task(r) for r in rows]

    async def list_pool(self, user_id: int) -> list[Task]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'pool'
                ORDER BY priority ASC, id DESC
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_task(r) for r in rows]

    async def move_to_pool(
        self, user_id: int, task_id: int, *, record_carry_over: bool = False
    ) -> Task | None:
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            if record_carry_over and row["planned_date"]:
                await conn.execute(
                    """
                    INSERT INTO task_history_events (user_id, task_id, event_date, action, task_title, created_at)
                    VALUES (?, ?, ?, 'carried_over', ?, ?)
                    """,
                    (user_id, task_id, row["planned_date"], row["title"], now),
                )
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'pool',
                    planned_date = NULL,
                    planned_time = NULL,
                    completed_at = NULL
                WHERE id = ?
                """,
                (task_id,),
            )
            await conn.commit()
            updated_cur = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            updated = await updated_cur.fetchone()
            return self._row_to_task(updated) if updated else None

    async def list_tasks_for_date(self, user_id: int, day_iso: str) -> list[Task]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND planned_date = ? AND status IN ('planned', 'done')
                ORDER BY
                    CASE WHEN status = 'done' THEN 1 ELSE 0 END ASC,
                    CASE WHEN planned_time IS NULL OR planned_time = '' THEN 1 ELSE 0 END ASC,
                    planned_time ASC,
                    priority ASC,
                    sort_order ASC,
                    id ASC
                """,
                (user_id, day_iso),
            )
            rows = await cursor.fetchall()
            return [self._row_to_task(r) for r in rows]

    async def list_pending_tasks_for_date(self, user_id: int, day_iso: str) -> list[Task]:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND planned_date = ? AND status = 'planned'
                ORDER BY priority ASC, planned_time ASC, id ASC
                """,
                (user_id, day_iso),
            )
            rows = await cursor.fetchall()
            return [self._row_to_task(r) for r in rows]

    async def get_day_plan(self, user_id: int, day_iso: str) -> DayPlan:
        async with self.db.connect() as conn:
            ev_cur = await conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE user_id = ? AND event_date = ?
                ORDER BY start_time ASC, id ASC
                """,
                (user_id, day_iso),
            )
            ev_rows = await ev_cur.fetchall()

            t_cur = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND planned_date = ? AND status IN ('planned', 'done')
                ORDER BY
                    CASE WHEN status = 'done' THEN 1 ELSE 0 END ASC,
                    CASE WHEN planned_time IS NULL OR planned_time = '' THEN 1 ELSE 0 END ASC,
                    planned_time ASC,
                    priority ASC,
                    sort_order ASC,
                    id ASC
                """,
                (user_id, day_iso),
            )
            t_rows = await t_cur.fetchall()

        events = [
            ScheduleEvent(
                id=r["id"],
                user_id=r["user_id"],
                event_date=r["event_date"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                title=r["title"],
                location=r["location"],
                notes=r["notes"],
                source=r["source"],
                is_done=bool(r["is_done"]),
                created_at=r["created_at"],
            )
            for r in ev_rows
        ]
        tasks = [self._row_to_task(r) for r in t_rows]
        return DayPlan(day=day_iso, schedule_events=events, tasks=tasks)

    async def toggle_done(self, user_id: int, task_id: int, fallback_date: str | None = None) -> Task | None:
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            current_status = row["status"]
            planned_date = row["planned_date"] or fallback_date
            if current_status == "done":
                new_status = "planned" if planned_date else "inbox"
                await conn.execute(
                    "UPDATE tasks SET status = ?, completed_at = NULL WHERE id = ?",
                    (new_status, task_id),
                )
            else:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'done',
                        planned_date = COALESCE(planned_date, ?),
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (planned_date, now, task_id),
                )
            await conn.commit()
            updated_cur = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            updated = await updated_cur.fetchone()
            return self._row_to_task(updated) if updated else None

    async def plan_task_for_date(
        self,
        user_id: int,
        task_id: int,
        target_date: str,
        *,
        planned_time: str | None = None,
        record_carry_over: bool = False,
    ) -> Task | None:
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            prev_date = row["planned_date"]
            carried_count = row["carried_over_count"]
            if record_carry_over and prev_date and prev_date != target_date:
                carried_count += 1
                await conn.execute(
                    """
                    INSERT INTO task_history_events (user_id, task_id, event_date, action, task_title, created_at)
                    VALUES (?, ?, ?, 'carried_over', ?, ?)
                    """,
                    (user_id, task_id, prev_date, row["title"], now),
                )

            new_time = planned_time if planned_time is not None else row["planned_time"]
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'planned',
                    planned_date = ?,
                    planned_time = ?,
                    completed_at = NULL,
                    carried_over_count = ?
                WHERE id = ?
                """,
                (target_date, new_time, carried_count, task_id),
            )
            await conn.commit()
            updated_cur = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            updated = await updated_cur.fetchone()
            return self._row_to_task(updated) if updated else None

    async def carry_over_all_pending(self, user_id: int, from_date: str, to_date: str) -> int:
        pending = await self.list_pending_tasks_for_date(user_id, from_date)
        count = 0
        for task in pending:
            res = await self.plan_task_for_date(
                user_id, task.id, to_date, record_carry_over=True
            )
            if res is not None:
                count += 1
        return count

    async def move_to_inbox(
        self, user_id: int, task_id: int, *, record_carry_over: bool = False
    ) -> Task | None:
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            if record_carry_over and row["planned_date"]:
                await conn.execute(
                    """
                    INSERT INTO task_history_events (user_id, task_id, event_date, action, task_title, created_at)
                    VALUES (?, ?, ?, 'carried_over', ?, ?)
                    """,
                    (user_id, task_id, row["planned_date"], row["title"], now),
                )
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'inbox',
                    planned_date = NULL,
                    planned_time = NULL,
                    completed_at = NULL
                WHERE id = ?
                """,
                (task_id,),
            )
            await conn.commit()
            updated_cur = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            updated = await updated_cur.fetchone()
            return self._row_to_task(updated) if updated else None

    async def set_priority(self, user_id: int, task_id: int, priority: int) -> Task | None:
        priority = max(1, min(3, priority))
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE tasks SET priority = ? WHERE id = ? AND user_id = ?",
                (priority, task_id, user_id),
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cur.fetchone()
            return self._row_to_task(row) if row else None

    async def cycle_priority(self, user_id: int, task_id: int) -> Task | None:
        task = await self.get_task(user_id, task_id)
        if not task:
            return None
        next_priority = {2: 1, 1: 3, 3: 2}.get(task.priority, 2)
        return await self.set_priority(user_id, task_id, next_priority)

    async def set_planned_time(self, user_id: int, task_id: int, hhmm: str | None) -> Task | None:
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE tasks SET planned_time = ? WHERE id = ? AND user_id = ?",
                (hhmm, task_id, user_id),
            )
            await conn.commit()
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cur.fetchone()
            return self._row_to_task(row) if row else None

    async def delete_task(self, user_id: int, task_id: int) -> bool:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "DELETE FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> Task:
        return Task(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            notes=row["notes"],
            status=row["status"],
            priority=row["priority"],
            planned_date=row["planned_date"],
            planned_time=row["planned_time"],
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            carried_over_count=row["carried_over_count"],
        )
