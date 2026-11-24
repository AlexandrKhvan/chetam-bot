from __future__ import annotations

import pytest

from app.bot.formatters import render_daily_history, render_day_plan, render_period_stats
from app.db.database import Database
from app.services.history_service import HistoryService
from app.services.schedule_service import ScheduleService
from app.services.task_service import TaskService


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "history_test.db")
    await database.init()
    await database.upsert_user(user_id=202, username="tester", first_name="Test")
    return database


async def test_daily_history_and_period_stats(db: Database):
    tasks = TaskService(db)
    schedule = ScheduleService(db)
    history = HistoryService(db)

    # Day 1 (2026-11-23): 1 done task, 1 carried over to next day
    t1 = await tasks.create_task(202, "Закрыть ДЗ #1", planned_date="2026-11-23")
    t2 = await tasks.create_task(202, "Подготовить презентацию", planned_date="2026-11-23")
    await tasks.toggle_done(202, t1.id)
    await tasks.plan_task_for_date(202, t2.id, "2026-11-24", record_carry_over=True)

    # Day 2 (2026-11-24): finish carried task + attend 1 class
    await tasks.toggle_done(202, t2.id)
    ev = await schedule.add_event(202, "2026-11-24", "09:00", "Матан", end_time="10:30")
    await schedule.toggle_done(202, ev.id)

    # Day 3 (2026-11-25): 1 done, 1 pending
    t3 = await tasks.create_task(202, "Решить задачи", planned_date="2026-11-25")
    await tasks.create_task(202, "Проверить почту", planned_date="2026-11-25")
    await tasks.toggle_done(202, t3.id)

    summary_23 = await history.get_daily_summary(202, "2026-11-23")
    assert len(summary_23.completed_tasks) == 1
    assert len(summary_23.carried_over_events) == 1
    assert summary_23.done_count == 1
    assert summary_23.total_count == 2

    stats = await history.get_period_stats(202, "2026-11-25", days=7)
    assert stats.streak_days == 3
    assert stats.total_done == 4  # 1 on 23rd + 2 on 24th + 1 on 25th
    assert stats.total_planned == 6  # 2 on 23rd + 2 on 24th + 2 on 25th

    # Smoke-test HTML renderers
    plan_25 = await tasks.get_day_plan(202, "2026-11-25")
    rendered_day = render_day_plan(plan_25, "2026-11-25")
    assert "Решить задачи" in rendered_day
    assert "Проверить почту" in rendered_day

    rendered_hist = render_daily_history(summary_23, "2026-11-25")
    assert "Перенесено" in rendered_hist

    rendered_stats = render_period_stats(stats)
    assert "3 дн." in rendered_stats
