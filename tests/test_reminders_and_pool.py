from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import Database
from app.main import BOT_DESCRIPTION, BOT_SHORT_DESCRIPTION
from app.services.reminder_service import ReminderService, parse_reminder_input
from app.services.task_service import TaskService
from app.web.server import create_app
from tests.test_webapp import _make_init_data


def test_bot_profile_description_limits():
    assert len(BOT_DESCRIPTION) <= 512
    assert len(BOT_SHORT_DESCRIPTION) <= 120


def test_parse_reminder_input_variants():
    tz = ZoneInfo("Asia/Yekaterinburg")
    now = datetime(2026, 11, 26, 12, 0, tzinfo=tz)

    r1 = parse_reminder_input("через 30 мин выключить плиту", "Asia/Yekaterinburg", now_local=now)
    assert r1 is not None
    assert r1.remind_at_local.hour == 12 and r1.remind_at_local.minute == 30
    assert r1.text == "Выключить плиту"
    assert r1.repeat_rule == ""

    r2 = parse_reminder_input("завтра в 10:15 сдать отчёт", "Asia/Yekaterinburg", now_local=now)
    assert r2 is not None
    assert r2.remind_at_local.date().isoformat() == "2026-11-27"
    assert r2.remind_at_local.strftime("%H:%M") == "10:15"
    assert r2.text == "Сдать отчёт"

    r3 = parse_reminder_input("каждый день в 22:00 пить витамины", "Asia/Yekaterinburg", now_local=now)
    assert r3 is not None
    assert r3.repeat_rule == "daily"
    assert r3.remind_at_local.strftime("%H:%M") == "22:00"
    assert r3.text == "Пить витамины"

    r4 = parse_reminder_input("28.11 в 14:00 зачёт по физике", "Asia/Yekaterinburg", now_local=now)
    assert r4 is not None
    assert r4.remind_at_local.date().isoformat() == "2026-11-28"
    assert r4.text == "Зачёт по физике"


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "rem_pool.db")
    await database.init()
    await database.upsert_user(user_id=505, username="alex", first_name="Alex")
    return database


async def test_pool_and_reminders_services(db: Database):
    tasks = TaskService(db)
    rems = ReminderService(db)

    p1 = await tasks.create_task(505, "Прочитать книгу по алгоритмам", initial_status="pool")
    assert p1.status == "pool"

    t_inb = await tasks.create_task(505, "Починить наушники")
    moved = await tasks.move_to_pool(505, t_inb.id)
    assert moved is not None and moved.status == "pool"

    pool = await tasks.list_pool(505)
    assert len(pool) == 2

    # Pull from pool into tomorrow
    planned = await tasks.plan_task_for_date(505, p1.id, "2026-11-27")
    assert planned is not None and planned.status == "planned"
    assert len(await tasks.list_pool(505)) == 1

    # Due one-shot and daily reminders
    past_utc = datetime.now(timezone.utc) - timedelta(minutes=2)
    r_once = await rems.create_reminder(505, "Позвонить маме", past_utc)
    r_daily = await rems.create_reminder(505, "Пить витамины", past_utc, repeat_rule="daily")

    due = await rems.list_due()
    assert len(due) == 2

    await rems.mark_triggered(r_once.id)
    await rems.mark_triggered(r_daily.id)

    active = await rems.list_active(505)
    assert len(active) == 1
    assert active[0].id == r_daily.id  # Daily advanced by +1 day!

    snoozed = await rems.snooze(505, r_once.id, minutes=15)
    assert snoozed is not None and snoozed.is_sent is False


def test_webapp_pool_and_reminders_api(tmp_path):
    token = "123456:TEST_TOKEN"
    settings = Settings(
        BOT_TOKEN=token,
        DATABASE_PATH=tmp_path / "webapp_pool_rem.db",
        ALLOWED_USER_IDS="888",
    )
    app = create_app(settings)
    headers = {"X-Telegram-Init-Data": _make_init_data(token, user_id=888)}

    with TestClient(app) as client:
        # Dump directly into pool
        res = client.post(
            "/api/tasks/dump",
            headers=headers,
            json={"text": "Разобрать шкаф, потом выучить Docker Compose", "target_bucket": "pool"},
        )
        assert res.status_code == 200
        assert res.json()["count"] == 2

        pool_res = client.get("/api/pool", headers=headers)
        assert pool_res.status_code == 200
        assert len(pool_res.json()["tasks"]) == 2
        tid = pool_res.json()["tasks"][0]["id"]

        # Create task reminder preset + custom reminder
        tr_res = client.post(f"/api/tasks/{tid}/remind", headers=headers, json={"preset": "15m"})
        assert tr_res.status_code == 200

        cr_res = client.post(
            "/api/reminders",
            headers=headers,
            json={"text": "через 45 мин проверить духовку"},
        )
        assert cr_res.status_code == 200
        rem_id = cr_res.json()["reminder"]["id"]

        list_res = client.get("/api/reminders", headers=headers)
        assert list_res.status_code == 200
        assert len(list_res.json()["reminders"]) == 2

        snz_res = client.post(
            f"/api/reminders/{rem_id}/snooze",
            headers=headers,
            json={"minutes": 30},
        )
        assert snz_res.status_code == 200
