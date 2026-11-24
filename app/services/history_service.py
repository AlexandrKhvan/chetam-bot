from __future__ import annotations

from datetime import date, timedelta

from app.db.database import Database
from app.db.models import DailySummary, PeriodStats, ScheduleEvent, Task, TaskHistoryEvent


class HistoryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_daily_summary(self, user_id: int, day_iso: str) -> DailySummary:
        async with self.db.connect() as conn:
            t_cur = await conn.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND planned_date = ? AND status IN ('planned', 'done')
                ORDER BY priority ASC, id ASC
                """,
                (user_id, day_iso),
            )
            t_rows = await t_cur.fetchall()

            h_cur = await conn.execute(
                """
                SELECT * FROM task_history_events
                WHERE user_id = ? AND event_date = ? AND action = 'carried_over'
                ORDER BY id ASC
                """,
                (user_id, day_iso),
            )
            h_rows = await h_cur.fetchall()

            ev_cur = await conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE user_id = ? AND event_date = ?
                ORDER BY start_time ASC, id ASC
                """,
                (user_id, day_iso),
            )
            ev_rows = await ev_cur.fetchall()

        completed_tasks: list[Task] = []
        pending_tasks: list[Task] = []
        for r in t_rows:
            task = Task(
                id=r["id"],
                user_id=r["user_id"],
                title=r["title"],
                notes=r["notes"],
                status=r["status"],
                priority=r["priority"],
                planned_date=r["planned_date"],
                planned_time=r["planned_time"],
                sort_order=r["sort_order"],
                created_at=r["created_at"],
                completed_at=r["completed_at"],
                carried_over_count=r["carried_over_count"],
            )
            if task.status == "done":
                completed_tasks.append(task)
            else:
                pending_tasks.append(task)

        carried_events = [
            TaskHistoryEvent(
                id=r["id"],
                user_id=r["user_id"],
                task_id=r["task_id"],
                event_date=r["event_date"],
                action=r["action"],
                task_title=r["task_title"],
                created_at=r["created_at"],
            )
            for r in h_rows
        ]
        schedule_events = [
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

        return DailySummary(
            day=day_iso,
            completed_tasks=completed_tasks,
            pending_tasks=pending_tasks,
            carried_over_events=carried_events,
            schedule_events=schedule_events,
        )

    async def get_period_stats(
        self, user_id: int, end_date_iso: str, days: int = 7
    ) -> PeriodStats:
        end_d = date.fromisoformat(end_date_iso)
        start_d = end_d - timedelta(days=days - 1)

        total_done = 0
        total_planned = 0
        breakdown: list[tuple[str, int, int]] = []

        for offset in range(days):
            cur_d = (start_d + timedelta(days=offset)).isoformat()
            summary = await self.get_daily_summary(user_id, cur_d)
            done = summary.done_count
            planned = summary.total_count
            total_done += done
            total_planned += planned
            breakdown.append((cur_d, done, planned))

        # Compute streak going backwards from end_date (if today has 0 done yet, check starting from yesterday)
        streak = 0
        check_d = end_d
        today_summary = await self.get_daily_summary(user_id, check_d.isoformat())
        if today_summary.done_count == 0:
            check_d = end_d - timedelta(days=1)

        for _ in range(60):
            s = await self.get_daily_summary(user_id, check_d.isoformat())
            if s.done_count > 0:
                streak += 1
                check_d -= timedelta(days=1)
            else:
                break

        return PeriodStats(
            days_count=days,
            start_date=start_d.isoformat(),
            end_date=end_d.isoformat(),
            total_done=total_done,
            total_planned=total_planned,
            streak_days=streak,
            daily_breakdown=breakdown,
        )
