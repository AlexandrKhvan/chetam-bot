from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from app.db.models import UserProfile

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'Asia/Yekaterinburg',
    evening_plan_time TEXT NOT NULL DEFAULT '21:00',
    morning_digest_time TEXT NOT NULL DEFAULT '08:00',
    evening_reminder_enabled INTEGER NOT NULL DEFAULT 1,
    morning_digest_enabled INTEGER NOT NULL DEFAULT 1,
    class_reminder_minutes INTEGER NOT NULL DEFAULT 15,
    study_group TEXT NOT NULL DEFAULT '',
    onboarded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'inbox',
    priority INTEGER NOT NULL DEFAULT 2,
    planned_date TEXT,
    planned_time TEXT,
    deadline_date TEXT,
    tags TEXT NOT NULL DEFAULT '',
    recurrence_rule TEXT NOT NULL DEFAULT '',
    parent_template_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    carried_over_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks (user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks (user_id, planned_date);

CREATE TABLE IF NOT EXISTS subtasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    is_done INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks (task_id, sort_order, id);

CREATE TABLE IF NOT EXISTS schedule_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    meeting_info TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    is_done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_schedule_user_date
    ON schedule_events (user_id, event_date, start_time);

CREATE TABLE IF NOT EXISTS shared_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code TEXT NOT NULL,
    event_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    meeting_info TEXT NOT NULL DEFAULT '',
    uploaded_by INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shared_group_date
    ON shared_schedules (group_code, event_date, start_time);

CREATE TABLE IF NOT EXISTS task_history_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id INTEGER,
    event_date TEXT NOT NULL,
    action TEXT NOT NULL,
    task_title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_history_user_date
    ON task_history_events (user_id, event_date);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id INTEGER,
    text TEXT NOT NULL,
    remind_at_utc TEXT NOT NULL,
    repeat_rule TEXT NOT NULL DEFAULT '',
    is_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_reminders_due
    ON reminders (is_sent, remind_at_utc);
CREATE INDEX IF NOT EXISTS idx_reminders_user
    ON reminders (user_id, is_sent, remind_at_utc);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    async def init(self) -> None:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as conn:
            await conn.executescript(SCHEMA_SQL)
            await self._ensure_column(conn, "users", "study_group", "TEXT NOT NULL DEFAULT ''")
            await self._ensure_column(
                conn, "users", "class_reminder_minutes", "INTEGER NOT NULL DEFAULT 15"
            )
            await self._ensure_column(conn, "users", "onboarded", "INTEGER NOT NULL DEFAULT 0")
            await self._ensure_column(conn, "tasks", "deadline_date", "TEXT")
            await self._ensure_column(conn, "tasks", "tags", "TEXT NOT NULL DEFAULT ''")
            await self._ensure_column(conn, "tasks", "recurrence_rule", "TEXT NOT NULL DEFAULT ''")
            await self._ensure_column(conn, "tasks", "parent_template_id", "INTEGER")
            await self._ensure_column(
                conn, "schedule_events", "meeting_info", "TEXT NOT NULL DEFAULT ''"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_user_deadline ON tasks (user_id, deadline_date)"
            )
            await conn.commit()

    @staticmethod
    async def _ensure_column(
        conn: aiosqlite.Connection, table: str, column: str, ddl_type: str
    ) -> None:
        cur = await conn.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in await cur.fetchall()}
        if column not in cols:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            await conn.close()

    async def upsert_user(
        self,
        user_id: int,
        username: str = "",
        first_name: str = "",
        default_timezone: str = "Asia/Yekaterinburg",
        default_evening_plan_time: str = "21:00",
        default_morning_digest_time: str = "08:00",
    ) -> UserProfile:
        now = utc_now_iso()
        async with self.connect() as conn:
            await conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, timezone,
                    evening_plan_time, morning_digest_time, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (
                    user_id,
                    username or "",
                    first_name or "",
                    default_timezone,
                    default_evening_plan_time,
                    default_morning_digest_time,
                    now,
                ),
            )
            await conn.commit()
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            assert row is not None
            return self._row_to_user(row)

    async def get_user(self, user_id: int) -> UserProfile | None:
        async with self.connect() as conn:
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return self._row_to_user(row) if row else None

    async def list_users(self) -> list[UserProfile]:
        async with self.connect() as conn:
            cursor = await conn.execute("SELECT * FROM users ORDER BY user_id ASC")
            rows = await cursor.fetchall()
            return [self._row_to_user(r) for r in rows]

    async def update_user_settings(
        self,
        user_id: int,
        *,
        timezone_name: str | None = None,
        evening_plan_time: str | None = None,
        morning_digest_time: str | None = None,
        evening_reminder_enabled: bool | None = None,
        morning_digest_enabled: bool | None = None,
        class_reminder_minutes: int | None = None,
        study_group: str | None = None,
        onboarded: bool | None = None,
    ) -> UserProfile | None:
        updates: list[str] = []
        params: list[object] = []
        if timezone_name is not None:
            updates.append("timezone = ?")
            params.append(timezone_name)
        if evening_plan_time is not None:
            updates.append("evening_plan_time = ?")
            params.append(evening_plan_time)
        if morning_digest_time is not None:
            updates.append("morning_digest_time = ?")
            params.append(morning_digest_time)
        if evening_reminder_enabled is not None:
            updates.append("evening_reminder_enabled = ?")
            params.append(int(evening_reminder_enabled))
        if morning_digest_enabled is not None:
            updates.append("morning_digest_enabled = ?")
            params.append(int(morning_digest_enabled))
        if class_reminder_minutes is not None:
            updates.append("class_reminder_minutes = ?")
            params.append(max(0, class_reminder_minutes))
        if study_group is not None:
            updates.append("study_group = ?")
            params.append(study_group.strip())
        if onboarded is not None:
            updates.append("onboarded = ?")
            params.append(int(onboarded))

        if not updates:
            return await self.get_user(user_id)

        params.append(user_id)
        async with self.connect() as conn:
            await conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                params,
            )
            await conn.commit()
            cursor = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return self._row_to_user(row) if row else None

    @staticmethod
    def _row_to_user(row: aiosqlite.Row) -> UserProfile:
        keys = set(row.keys())
        return UserProfile(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            timezone=row["timezone"],
            evening_plan_time=row["evening_plan_time"],
            morning_digest_time=row["morning_digest_time"],
            evening_reminder_enabled=bool(row["evening_reminder_enabled"]),
            morning_digest_enabled=bool(row["morning_digest_enabled"]),
            class_reminder_minutes=(
                int(row["class_reminder_minutes"]) if "class_reminder_minutes" in keys else 15
            ),
            study_group=row["study_group"] if "study_group" in keys else "",
            onboarded=bool(row["onboarded"]) if "onboarded" in keys else False,
            created_at=row["created_at"],
        )
