from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import aiosqlite

from app.db.database import Database, utc_now_iso
from app.db.models import DayPlan, ScheduleEvent, Subtask, Task


def normalize_tags(tags: list[str] | str | None) -> list[str]:
    if not tags:
        return []
    raw_list = tags.split(",") if isinstance(tags, str) else list(tags)
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_list:
        t = item.strip().lstrip("#").lower()
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    return cleaned


def recurrence_matches_date(rule: str, target_date: date) -> bool:
    if not rule:
        return False
    wd = target_date.weekday()  # 0=Mon..6=Sun
    if rule == "daily":
        return True
    if rule == "weekdays":
        return wd < 5
    if rule.startswith("days:"):
        allowed = {int(x) for x in rule[5:].split(",") if x.strip().isdigit()}
        return wd in allowed
    return False


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
        deadline_date: str | None = None,
        tags: list[str] | None = None,
        recurrence_rule: str = "",
        parent_template_id: int | None = None,
        priority: int = 2,
        initial_status: str = "inbox",
        today_iso: str | None = None,
    ) -> Task:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Task title cannot be empty")
        status = "planned" if planned_date else ("pool" if initial_status == "pool" else "inbox")
        eff_priority = priority
        if deadline_date and status != "done":
            ref_today = date.fromisoformat(today_iso) if today_iso else date.today()
            try:
                days_left = (date.fromisoformat(deadline_date) - ref_today).days
                if days_left <= 3:
                    eff_priority = 1
            except ValueError:
                deadline_date = None

        tag_csv = ",".join(normalize_tags(tags))
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO tasks (
                    user_id, title, notes, status, priority,
                    planned_date, planned_time, deadline_date,
                    tags, recurrence_rule, parent_template_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    clean_title,
                    notes.strip(),
                    status,
                    eff_priority,
                    planned_date,
                    planned_time,
                    deadline_date,
                    tag_csv,
                    recurrence_rule.strip(),
                    parent_template_id,
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

    async def escalate_deadline_priorities(self, user_id: int, today_iso: str) -> int:
        """Automatically bumps priority to 1 (high/urgent) for open tasks whose deadline is <= 3 days away."""
        cutoff = (date.fromisoformat(today_iso) + timedelta(days=3)).isoformat()
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                UPDATE tasks
                SET priority = 1
                WHERE user_id = ?
                  AND status IN ('inbox', 'pool', 'planned')
                  AND deadline_date IS NOT NULL
                  AND deadline_date != ''
                  AND deadline_date <= ?
                  AND priority > 1
                """,
                (user_id, cutoff),
            )
            await conn.commit()
            return cur.rowcount

    async def materialize_recurring_tasks(self, user_id: int, day_iso: str) -> int:
        """Creates daily/weekly habit task instances on day_iso from recurring templates without duplicating."""
        target_d = date.fromisoformat(day_iso)
        created = 0
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ?
                  AND recurrence_rule != ''
                  AND parent_template_id IS NULL
                  AND status != 'cancelled'
                """,
                (user_id,),
            )
            templates = await cur.fetchall()
            now = utc_now_iso()
            for tmpl in templates:
                if not recurrence_matches_date(tmpl["recurrence_rule"], target_d):
                    continue
                if tmpl["planned_date"] == day_iso:
                    continue
                exists_cur = await conn.execute(
                    """
                    SELECT id FROM tasks
                    WHERE user_id = ? AND planned_date = ? AND (parent_template_id = ? OR id = ?)
                    LIMIT 1
                    """,
                    (user_id, day_iso, tmpl["id"], tmpl["id"]),
                )
                if await exists_cur.fetchone():
                    continue
                await conn.execute(
                    """
                    INSERT INTO tasks (
                        user_id, title, notes, status, priority,
                        planned_date, planned_time, deadline_date,
                        tags, recurrence_rule, parent_template_id, created_at
                    )
                    VALUES (?, ?, ?, 'planned', ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        tmpl["title"],
                        tmpl["notes"],
                        tmpl["priority"],
                        day_iso,
                        tmpl["planned_time"],
                        tmpl["tags"],
                        tmpl["recurrence_rule"],
                        tmpl["id"],
                        now,
                    ),
                )
                created += 1
            if created:
                await conn.commit()
        return created

    async def get_task(self, user_id: int, task_id: int) -> Task | None:
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            task = self._row_to_task(row)
            await self._attach_subtasks(conn, [task])
            return task

    async def list_inbox(self, user_id: int, *, today_iso: str | None = None) -> list[Task]:
        if today_iso:
            await self.escalate_deadline_priorities(user_id, today_iso)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'inbox'
                ORDER BY
                    priority ASC,
                    CASE WHEN deadline_date IS NULL OR deadline_date = '' THEN 1 ELSE 0 END ASC,
                    deadline_date ASC,
                    id DESC
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            tasks = [self._row_to_task(r) for r in rows]
            await self._attach_subtasks(conn, tasks)
            return tasks

    async def list_pool(
        self, user_id: int, *, tag: str | None = None, today_iso: str | None = None
    ) -> list[Task]:
        if today_iso:
            await self.escalate_deadline_priorities(user_id, today_iso)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'pool'
                ORDER BY
                    priority ASC,
                    CASE WHEN deadline_date IS NULL OR deadline_date = '' THEN 1 ELSE 0 END ASC,
                    deadline_date ASC,
                    id DESC
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            tasks = [self._row_to_task(r) for r in rows]
            if tag:
                clean_tag = tag.strip().lstrip("#").lower()
                tasks = [t for t in tasks if clean_tag in t.tags]
            await self._attach_subtasks(conn, tasks)
            return tasks

    async def list_pool_tags(self, user_id: int) -> list[str]:
        tasks = await self.list_pool(user_id)
        tags: set[str] = set()
        for t in tasks:
            tags.update(t.tags)
        return sorted(tags)

    async def list_upcoming_deadlines(
        self, user_id: int, today_iso: str, *, limit: int = 8
    ) -> list[Task]:
        await self.escalate_deadline_priorities(user_id, today_iso)
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ?
                  AND status IN ('inbox', 'pool', 'planned')
                  AND deadline_date IS NOT NULL
                  AND deadline_date != ''
                ORDER BY deadline_date ASC, priority ASC, id ASC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()
            tasks = [self._row_to_task(r) for r in rows]
            await self._attach_subtasks(conn, tasks)
            return tasks

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
            tasks = [self._row_to_task(r) for r in rows]
            await self._attach_subtasks(conn, tasks)
            return tasks

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

    async def get_day_plan(
        self, user_id: int, day_iso: str, *, today_iso: str | None = None
    ) -> DayPlan:
        await self.escalate_deadline_priorities(user_id, today_iso or day_iso)
        await self.materialize_recurring_tasks(user_id, day_iso)

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
            tasks = [self._row_to_task(r) for r in t_rows]
            await self._attach_subtasks(conn, tasks)

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
                meeting_info=r["meeting_info"] if "meeting_info" in r.keys() else "",
                source=r["source"],
                is_done=bool(r["is_done"]),
                created_at=r["created_at"],
            )
            for r in ev_rows
        ]
        return DayPlan(day=day_iso, schedule_events=events, tasks=tasks)

    # --- Subtasks ---

    async def add_subtask(self, user_id: int, task_id: int, title: str) -> Subtask | None:
        clean = title.strip()
        if not clean:
            return None
        task = await self.get_task(user_id, task_id)
        if not task:
            return None
        now = utc_now_iso()
        async with self.db.connect() as conn:
            cur = await conn.execute(
                "INSERT INTO subtasks (task_id, title, is_done, sort_order, created_at) VALUES (?, ?, 0, ?, ?)",
                (task_id, clean, len(task.subtasks), now),
            )
            sub_id = cur.lastrowid
            await conn.commit()
            row_cur = await conn.execute("SELECT * FROM subtasks WHERE id = ?", (sub_id,))
            row = await row_cur.fetchone()
            assert row is not None
            return self._row_to_subtask(row)

    async def toggle_subtask(self, user_id: int, subtask_id: int) -> Subtask | None:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                SELECT s.* FROM subtasks s
                JOIN tasks t ON t.id = s.task_id
                WHERE s.id = ? AND t.user_id = ?
                """,
                (subtask_id, user_id),
            )
            row = await cur.fetchone()
            if not row:
                return None
            new_val = 0 if row["is_done"] else 1
            await conn.execute("UPDATE subtasks SET is_done = ? WHERE id = ?", (new_val, subtask_id))
            await conn.commit()
            upd = await conn.execute("SELECT * FROM subtasks WHERE id = ?", (subtask_id,))
            u_row = await upd.fetchone()
            return self._row_to_subtask(u_row) if u_row else None

    async def delete_subtask(self, user_id: int, subtask_id: int) -> bool:
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                DELETE FROM subtasks
                WHERE id = ? AND task_id IN (SELECT id FROM tasks WHERE user_id = ?)
                """,
                (subtask_id, user_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def set_deadline(
        self, user_id: int, task_id: int, deadline_date: str | None, *, today_iso: str | None = None
    ) -> Task | None:
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE tasks SET deadline_date = ? WHERE id = ? AND user_id = ?",
                (deadline_date, task_id, user_id),
            )
            await conn.commit()
        if deadline_date:
            await self.escalate_deadline_priorities(user_id, today_iso or date.today().isoformat())
        return await self.get_task(user_id, task_id)

    async def set_tags(self, user_id: int, task_id: int, tags: list[str]) -> Task | None:
        csv_tags = ",".join(normalize_tags(tags))
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE tasks SET tags = ? WHERE id = ? AND user_id = ?",
                (csv_tags, task_id, user_id),
            )
            await conn.commit()
        return await self.get_task(user_id, task_id)

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

    async def _attach_subtasks(self, conn: aiosqlite.Connection, tasks: list[Task]) -> None:
        if not tasks:
            return
        ids = [t.id for t in tasks]
        placeholders = ",".join("?" for _ in ids)
        cur = await conn.execute(
            f"SELECT * FROM subtasks WHERE task_id IN ({placeholders}) ORDER BY sort_order ASC, id ASC",
            ids,
        )
        rows = await cur.fetchall()
        grouped: dict[int, list[Subtask]] = defaultdict(list)
        for r in rows:
            grouped[r["task_id"]].append(self._row_to_subtask(r))
        for t in tasks:
            t.subtasks = grouped.get(t.id, [])

    @staticmethod
    def _row_to_subtask(row: aiosqlite.Row) -> Subtask:
        return Subtask(
            id=row["id"],
            task_id=row["task_id"],
            title=row["title"],
            is_done=bool(row["is_done"]),
            sort_order=row["sort_order"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> Task:
        keys = set(row.keys())
        return Task(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            notes=row["notes"],
            status=row["status"],
            priority=row["priority"],
            planned_date=row["planned_date"],
            planned_time=row["planned_time"],
            deadline_date=row["deadline_date"] if "deadline_date" in keys else None,
            tags=normalize_tags(row["tags"]) if "tags" in keys else [],
            recurrence_rule=row["recurrence_rule"] if "recurrence_rule" in keys else "",
            parent_template_id=row["parent_template_id"] if "parent_template_id" in keys else None,
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            carried_over_count=row["carried_over_count"],
        )
