from __future__ import annotations

import pytest

from app.db.database import Database
from app.db.models import ParsedScheduleItem
from app.services.schedule_service import ScheduleService
from app.services.task_service import TaskService


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    await database.upsert_user(user_id=101, username="student", first_name="Alex")
    return database


async def test_inbox_and_day_plan_workflow(db: Database):
    tasks = TaskService(db)

    t1 = await tasks.create_task(101, "Купить тетрадь")
    assert t1.status == "inbox"
    assert t1.planned_date is None

    bulk = await tasks.create_many_inbox(101, ["- Сделать лабу", "• Повторить матан", "   "])
    assert len(bulk) == 2

    inbox = await tasks.list_inbox(101)
    assert len(inbox) == 3

    planned = await tasks.plan_task_for_date(101, t1.id, "2026-11-25", planned_time="18:30")
    assert planned is not None
    assert planned.status == "planned"
    assert planned.planned_date == "2026-11-25"
    assert planned.planned_time == "18:30"

    toggled = await tasks.toggle_done(101, t1.id)
    assert toggled is not None
    assert toggled.status == "done"
    assert toggled.completed_at is not None

    plan = await tasks.get_day_plan(101, "2026-11-25")
    assert plan.total_tasks == 1
    assert plan.done_tasks == 1
    assert plan.completion_rate == 1.0


async def test_carry_over_records_history(db: Database):
    tasks = TaskService(db)
    t1 = await tasks.create_task(101, "Дочитать главу", planned_date="2026-11-25")
    t2 = await tasks.create_task(101, "Написать отчёт", planned_date="2026-11-25")
    await tasks.toggle_done(101, t1.id)

    moved = await tasks.carry_over_all_pending(101, "2026-11-25", "2026-11-26")
    assert moved == 1

    t2_after = await tasks.get_task(101, t2.id)
    assert t2_after is not None
    assert t2_after.planned_date == "2026-11-26"
    assert t2_after.carried_over_count == 1

    day_25 = await tasks.get_day_plan(101, "2026-11-25")
    assert len(day_25.tasks) == 1
    assert day_25.tasks[0].id == t1.id

    day_26 = await tasks.get_day_plan(101, "2026-11-26")
    assert len(day_26.tasks) == 1
    assert day_26.tasks[0].id == t2.id


async def test_schedule_import_replace_and_toggle(db: Database):
    schedule = ScheduleService(db)
    items = [
        ParsedScheduleItem(
            event_date="2026-11-25",
            start_time="09:00",
            end_time="10:30",
            title="Математический анализ",
            location="ауд. 305",
        ),
        ParsedScheduleItem(
            event_date="2026-11-25",
            start_time="10:45",
            end_time="12:15",
            title="Алгоритмы",
            location="ауд. 412",
        ),
    ]
    saved = await schedule.import_parsed_events(101, items, source="docx", replace_dates=True)
    assert saved == 2

    events = await schedule.list_events_for_date(101, "2026-11-25")
    assert len(events) == 2
    assert events[0].start_time == "09:00"

    toggled = await schedule.toggle_done(101, events[0].id)
    assert toggled is not None
    assert toggled.is_done is True

    # Replacing same date overwrites previous classes
    new_items = [
        ParsedScheduleItem(
            event_date="2026-11-25",
            start_time="13:00",
            end_time="14:30",
            title="Физика",
            location="ауд. 201",
        )
    ]
    await schedule.import_parsed_events(101, new_items, source="docx", replace_dates=True)
    events_after = await schedule.list_events_for_date(101, "2026-11-25")
    assert len(events_after) == 1
    assert events_after[0].title == "Физика"
